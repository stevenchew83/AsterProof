from django.contrib import admin

from .models import ProblemDifficultyVote
from .models import ProblemFavourite
from .models import ProblemProgress
from .models import ProblemQualityVote

admin.site.register(ProblemProgress)
admin.site.register(ProblemFavourite)
admin.site.register(ProblemDifficultyVote)
admin.site.register(ProblemQualityVote)
