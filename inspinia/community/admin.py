from django.contrib import admin

from .models import Comment
from .models import CommentReaction
from .models import ContentReport
from .models import PublicSolution
from .models import SolutionVote
from .models import TrustedSuggestion

admin.site.register(PublicSolution)
admin.site.register(SolutionVote)
admin.site.register(Comment)
admin.site.register(CommentReaction)
admin.site.register(ContentReport)
admin.site.register(TrustedSuggestion)
