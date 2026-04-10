from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def ranking_table_view(request):
    return render(request, "pages/rankings/ranking-table.html", {})

