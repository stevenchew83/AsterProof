"""Bound anonymous exports to mathematical fragments and short compiler jobs."""

import re
from contextlib import contextmanager
from uuid import uuid4

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils.crypto import salted_hmac

PUBLIC_PDF_TIMEOUT = 20
PUBLIC_PDF_CHARACTER_LIMIT = 32_000
# Public input is a fragment, never a preamble, package, file path, or TeX program.
_ALLOWED_COMMANDS = frozenset(r"""
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi
rho varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma
Upsilon Phi Psi Omega frac dfrac tfrac cfrac binom dbinom tbinom sqrt root overline underline overbrace
underbrace overset underset stackrel substack text textrm textsf texttt textbf textit emph mathrm mathit
mathbf mathsf mathtt mathcal mathbb mathfrak boldsymbol operatorname displaystyle textstyle scriptstyle
scriptscriptstyle left right middle big Big bigg Bigg bigl bigr Bigl Bigr biggl biggr Biggl Biggr
langle rangle lvert rvert lVert rVert vert Vert lfloor rfloor lceil rceil backslash
sum prod coprod int iint iiint oint lim liminf limsup min max inf sup gcd lcm det dim ker
sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh log ln exp arg deg hom Pr
le leq ge geq neq ne lt gt equiv sim simeq approx cong propto in notin ni subset subseteq supset supseteq
nsubseteq nsupseteq prec succ preceq succeq parallel nparallel perp mid nmid models vdash dashv
cdot times div pm mp ast star circ bullet cap cup setminus smallsetminus sqcap sqcup uplus
oplus ominus otimes oslash odot wedge vee land lor neg lnot forall exists nexists emptyset varnothing
infty partial nabla ell hbar Re Im wp aleph angle triangle square diamond triangleleft triangleright
rightarrow leftarrow leftrightarrow Rightarrow Leftarrow Leftrightarrow to gets mapsto longrightarrow
longleftarrow longleftrightarrow Longrightarrow Longleftarrow Longleftrightarrow implies iff uparrow
downarrow updownarrow Uparrow Downarrow Updownarrow hookrightarrow hookleftarrow
ldots cdots vdots ddots dots dotsc dotsb quad qquad enspace thinspace medspace thickspace
hat widehat bar vec tilde widetilde dot ddot acute grave breve check mathring boxed cancel phantom hphantom
vphantom smash strut underleftarrow underrightarrow overleftarrow overrightarrow pmod mod bmod
begin end item label ref eqref tag notag nonumber limits nolimits
textbackslash textasciitilde textasciicircum ensuremath
""".split())  # noqa: SIM905
_ALLOWED_SYMBOLS = frozenset("\\{}$%&#_ ,:;!|[]()/^~'`\n\r")
_ALLOWED_ENVIRONMENTS = frozenset({
    "aligned", "alignedat", "gathered", "split", "cases", "matrix", "pmatrix", "bmatrix", "Bmatrix",
    "vmatrix", "Vmatrix", "smallmatrix", "align", "align*", "gather", "gather*", "equation", "equation*",
    "enumerate", "itemize",
})
_COMMAND = re.compile(r"\\([a-zA-Z@]+|[^a-zA-Z@])")
_ENVIRONMENT = re.compile(r"\s*\{([a-zA-Z*]+)\}")
_MAX_GROUP_DEPTH = 32
_ASCII_SPACE = 32


def validate_public_latex(value):
    if "^^" in value or any(ord(char) < _ASCII_SPACE and char not in "\r\n\t" for char in value):
        message = "Use ordinary text and mathematical LaTeX fragments."
        raise ValidationError(message)
    depth = 0
    previous = 0
    # Ignore escaped braces when measuring nesting; all control sequences are checked.
    for match in _COMMAND.finditer(value):
        depth = _check_groups(value[previous:match.start()], depth)
        command = match[1]
        if len(command) == 1 and command in _ALLOWED_SYMBOLS:
            previous = match.end()
            continue
        if command not in _ALLOWED_COMMANDS:
            message = "The public PDF tool does not support \\%(command)s."
            raise ValidationError(message, params={"command": command})
        if command in {"begin", "end"}:
            environment = _ENVIRONMENT.match(value, match.end())
            if not environment or environment[1] not in _ALLOWED_ENVIRONMENTS:
                message = "Use a math or list environment, such as aligned, cases, or enumerate."
                raise ValidationError(message)
        previous = match.end()
    _check_groups(value[previous:], depth)


def _check_groups(value, depth):
    for char in value:
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        if depth > _MAX_GROUP_DEPTH:
            message = "Use fewer nested groups in this equation."
            raise ValidationError(message)
    return depth


def _consume_limit(label, value, maximum):
    key = "public-solution-pdf:" + label + ":" + salted_hmac("solution-pdf-rate", value).hexdigest()
    cache.add(key, 0, timeout=60)
    count = cache.incr(key)
    return isinstance(count, int) and count <= maximum


@contextmanager
def public_pdf_slot(request):
    key = None
    token = uuid4().hex
    try:
        # Do not trust client-provided forwarding headers. This is conservative behind a proxy.
        address = request.META.get("REMOTE_ADDR", "unknown")
        if _consume_limit("address", address, 6) and _consume_limit("all", "all", 30):
            for index in range(2):
                candidate = f"public-solution-pdf:slot:{index}"
                if cache.add(candidate, token, timeout=PUBLIC_PDF_TIMEOUT + 20):
                    key = candidate
                    break
    except (ValueError, OSError):
        key = None
    try:
        yield key is not None
    finally:
        if key and cache.get(key) == token:
            cache.delete(key)
