from django.contrib import admin

from .models import ActivityEvent
from .models import ProblemList
from .models import ProblemListItem

admin.site.register(ProblemList)
admin.site.register(ProblemListItem)
admin.site.register(ActivityEvent)
