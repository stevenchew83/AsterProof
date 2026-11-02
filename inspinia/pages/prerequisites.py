"""Curator-only prerequisite edits and non-mutating, revision-guarded readers."""

from collections import defaultdict
from collections import deque

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import transaction

from inspinia.pages.catalogue_models import CatalogueConcept
from inspinia.pages.catalogue_models import CatalogueState
from inspinia.pages.prerequisite_models import CataloguePrerequisite
from inspinia.pages.prerequisite_models import PrerequisiteGraphState

MAX_GRAPH_NODES = 5000
MAX_GRAPH_EDGES = 10000
EDGE_NODES = 2


def _require_curator(user):
    from inspinia.learning.permissions import require_publisher

    require_publisher(user)
    if not settings.LEARNING_MODULE_ENABLED or not settings.LEARNING_PUBLICATION_ENABLED:
        msg = "Prerequisite curation is not enabled."
        raise PermissionDenied(msg)


def _canonical_map():
    redirects = dict(CatalogueConcept.objects.values_list("pk", "redirect_id")[: MAX_GRAPH_NODES + 1])
    if len(redirects) > MAX_GRAPH_NODES:
        msg = "The prerequisite graph exceeds the reviewed node limit."
        raise ValidationError(msg)
    result = {}
    for identifier in redirects:
        current, seen = identifier, set()
        while redirects.get(current):
            if current in seen:
                msg = "Catalogue redirects contain a cycle."
                raise ValidationError(msg)
            seen.add(current)
            current = redirects[current]
        if current not in redirects:
            msg = "A catalogue redirect target is unavailable."
            raise ValidationError(msg)
        result[identifier] = current
    return result


def _normalised_edges(edges, canonical):  # noqa: C901 - Redirect normalization and bounded DAG verification.
    edges = list(edges)
    if len(edges) > MAX_GRAPH_EDGES:
        msg = "The prerequisite graph exceeds the reviewed edge limit."
        raise ValidationError(msg)
    resolved = set()
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != EDGE_NODES:
            msg = "Each prerequisite needs a prerequisite and dependent concept."
            raise ValidationError(msg)
        source, target = edge
        if source not in canonical or target not in canonical:
            msg = "A prerequisite references an unknown concept."
            raise ValidationError(msg)
        source, target = canonical[source], canonical[target]
        if source == target:
            msg = "A concept cannot be its own prerequisite."
            raise ValidationError(msg)
        resolved.add((source, target))
    incoming = defaultdict(int)
    outgoing = defaultdict(set)
    nodes = set()
    for source, target in resolved:
        nodes.update((source, target))
        outgoing[source].add(target)
        incoming[target] += 1
    ready = deque(sorted(node for node in nodes if incoming[node] == 0))
    visited = 0
    while ready:
        source = ready.popleft()
        visited += 1
        for target in outgoing[source]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if visited != len(nodes):
        msg = "Pedagogical prerequisites must not contain a directed cycle."
        raise ValidationError(msg)
    return sorted(resolved)


def _locked_state():
    catalogue = CatalogueState.objects.select_for_update().filter(pk=1).first()
    if catalogue is None:
        msg = "The catalogue state is unavailable."
        raise ValidationError(msg)
    state, _ = PrerequisiteGraphState.objects.select_for_update().get_or_create(singleton_key=1)
    return catalogue, state


@transaction.atomic
def replace_prerequisites(*, user, edges, expected_version):
    """Approve one complete edge change under the global graph lock."""
    _require_curator(user)
    catalogue, state = _locked_state()
    if type(expected_version) is not int or state.version != expected_version:
        msg = "Prerequisites changed. Reload and review the graph again."
        raise ValidationError(msg)
    normalised = _normalised_edges(edges, _canonical_map())
    old = set(CataloguePrerequisite.objects.values_list("prerequisite_id", "dependent_id"))
    wanted = set(normalised)
    for source, target in old - wanted:
        CataloguePrerequisite.objects.filter(prerequisite_id=source, dependent_id=target).delete()
    CataloguePrerequisite.objects.bulk_create(
        [
            CataloguePrerequisite(prerequisite_id=source, dependent_id=target, approved_by=user)
            for source, target in sorted(wanted - old)
        ],
    )
    state.version += 1
    state.validated_catalogue_revision = catalogue.source_revision
    state.is_valid = True
    state.snapshot = [list(edge) for edge in normalised]
    state.save(update_fields=["version", "validated_catalogue_revision", "is_valid", "snapshot", "updated_at"])
    return state


@transaction.atomic
def set_prerequisite(*, user, prerequisite_id, dependent_id, expected_version, remove=False):
    _require_curator(user)
    _locked_state()
    edges = set(CataloguePrerequisite.objects.values_list("prerequisite_id", "dependent_id"))
    edge = (prerequisite_id, dependent_id)
    if remove:
        edges.discard(edge)
    else:
        edges.add(edge)
    return replace_prerequisites(user=user, edges=sorted(edges), expected_version=expected_version)


@transaction.atomic
def revalidate_graph():
    """Maintenance-only derived validation; never approve or rewrite source edges."""
    catalogue, state = _locked_state()
    try:
        edges = _normalised_edges(
            CataloguePrerequisite.objects.values_list("prerequisite_id", "dependent_id"),
            _canonical_map(),
        )
    except ValidationError:
        state.is_valid = False
        state.snapshot = []
    else:
        state.is_valid = True
        state.snapshot = [list(edge) for edge in edges]
    state.validated_catalogue_revision = catalogue.source_revision
    state.save(update_fields=["validated_catalogue_revision", "is_valid", "snapshot", "updated_at"])
    return state


def prerequisite_context(concept_id):
    """Read the already-validated graph; a GET never rebuilds it."""
    from inspinia.pages.catalogue_browser import canonical_concept

    state = PrerequisiteGraphState.objects.filter(pk=1).first()
    marker = CatalogueState.objects.filter(pk=1).values_list("source_revision", flat=True).first()
    if not state or not state.is_valid or marker is None or state.validated_catalogue_revision != marker:
        return {"available": False, "version": state.version if state else 0, "prerequisites": [], "dependents": []}
    concept = canonical_concept(str(concept_id))
    if concept is None:
        return {"available": False, "version": state.version, "prerequisites": [], "dependents": []}
    before = {source for source, target in state.snapshot if target == concept.pk}
    after = {target for source, target in state.snapshot if source == concept.pk}
    names = dict(CatalogueConcept.objects.filter(pk__in=before | after).values_list("pk", "name"))
    return {
        "available": True,
        "version": state.version,
        "prerequisites": [{"id": key, "name": names[key]} for key in sorted(before) if key in names],
        "dependents": [{"id": key, "name": names[key]} for key in sorted(after) if key in names],
    }
