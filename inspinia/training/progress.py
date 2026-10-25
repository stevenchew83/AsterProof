"""Published roadmap progress, without submissions, comments, or editing controls."""

from django.db.models import Count
from django.db.models import Q

from inspinia.training.models import Submission
from inspinia.training.models import Subtopic
from inspinia.training.services import get_user_current_level
from inspinia.training.services import get_user_total_points


def training_progress_summary(user) -> dict:
    subtopics = (
        Subtopic.objects.filter(is_published=True, topic__is_published=True)
        .select_related("topic")
        .annotate(
            material_total=Count("materials", filter=Q(materials__is_published=True), distinct=True),
            material_done=Count(
                "materials",
                filter=Q(materials__is_published=True, materials__completions__user=user),
                distinct=True,
            ),
            problem_total=Count("problems", filter=Q(problems__is_published=True), distinct=True),
            problem_done=Count(
                "problems",
                filter=Q(
                    problems__is_published=True,
                    problems__submissions__user=user,
                    problems__submissions__status__in=[
                        Submission.Status.ACCEPTED,
                        Submission.Status.PARTIALLY_ACCEPTED,
                    ],
                ),
                distinct=True,
            ),
        )
        .order_by("topic__order", "topic__id", "order", "title", "id")
    )
    topics = {}
    next_subtopic = None
    for subtopic in subtopics:
        total = subtopic.material_total + subtopic.problem_total
        completed = subtopic.material_done + subtopic.problem_done
        row = {
            "title": subtopic.title,
            "total": total,
            "completed": completed,
            "percent": round(completed / total * 100) if total else 0,
        }
        topic = topics.setdefault(
            subtopic.topic_id,
            {"title": subtopic.topic.title, "subtopics": [], "total": 0, "completed": 0},
        )
        topic["subtopics"].append(row)
        topic["total"] += total
        topic["completed"] += completed
        if next_subtopic is None and total and completed < total:
            next_subtopic = {"title": subtopic.title, "topic": subtopic.topic.title}
    for topic in topics.values():
        topic["percent"] = round(topic["completed"] / topic["total"] * 100) if topic["total"] else 0
    return {
        "topics": list(topics.values()),
        "next_subtopic": next_subtopic,
        "level": get_user_current_level(user),
        "points": get_user_total_points(user),
    }
