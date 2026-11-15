from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.accounts.views import LoginView, LogoutView, MeView, RefreshView, TechnicianListView
from apps.ai.views import AnomalyListView, AskManualsView, ExplainAnomalyView, NLQueryView
from apps.dashboard.views import DashboardView
from apps.fleet.views import IngestFlightView
from apps.maintenance.views import AirworthinessView, DueListView

from .api import router


def health(request):
    """Liveness + DB check used by Docker healthchecks and the deploy platform."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/auth/login/", LoginView.as_view()),
    path("api/auth/refresh/", RefreshView.as_view()),
    path("api/auth/logout/", LogoutView.as_view()),
    path("api/auth/me/", MeView.as_view()),
    path("api/technicians/", TechnicianListView.as_view()),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    path("api/ai/ask/", AskManualsView.as_view()),
    path("api/ai/query/", NLQueryView.as_view()),
    path("api/ai/anomalies/", AnomalyListView.as_view()),
    path("api/ai/anomalies/explain/", ExplainAnomalyView.as_view()),
    path("api/ingest/flights/", IngestFlightView.as_view()),
    path("api/dashboard/", DashboardView.as_view()),
    path("api/due-items/", DueListView.as_view()),
    path("api/airworthiness/", AirworthinessView.as_view()),
    path("api/", include(router.urls)),
]
