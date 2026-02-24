from django.contrib import admin

from .models import FeedbackItem
from .models import FeedbackStatusEvent

admin.site.register(FeedbackItem)
admin.site.register(FeedbackStatusEvent)
