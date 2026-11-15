"""
Login / refresh / logout.

The refresh token travels only in an httpOnly cookie, so JavaScript (and any
XSS payload) can't read it. The access token is returned in the JSON body and
the frontend keeps it in memory only. D-005.
"""

from django.conf import settings
from rest_framework import permissions, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.services import record

from .models import User
from .permissions import IsAdmin
from .serializers import MeSerializer, UserSerializer


def _set_refresh_cookie(response: Response, refresh: str) -> None:
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite="Strict",
        path="/api/auth/",
    )


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = TokenObtainPairSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed:
            # Same message for "no such user" and "wrong password": don't leak which usernames exist.
            return Response({"detail": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        user = serializer.user
        response = Response({"access": serializer.validated_data["access"], "user": MeSerializer(user).data})
        _set_refresh_cookie(response, serializer.validated_data["refresh"])
        return response


class RefreshView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def post(self, request):
        token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not token:
            return Response({"detail": "No refresh token"}, status=status.HTTP_401_UNAUTHORIZED)
        serializer = TokenRefreshSerializer(data={"refresh": token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            return Response({"detail": "Invalid refresh token"}, status=status.HTTP_401_UNAUTHORIZED)
        response = Response({"access": serializer.validated_data["access"]})
        if "refresh" in serializer.validated_data:  # rotation is on
            _set_refresh_cookie(response, serializer.validated_data["refresh"])
        return response


class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def post(self, request):
        token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if token:
            try:
                RefreshToken(token).blacklist()  # server-side revoke
            except TokenError:
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(settings.REFRESH_COOKIE_NAME, path="/api/auth/")
        return response


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class UserViewSet(viewsets.ModelViewSet):
    """User management: ADMIN only, for reads and writes."""

    queryset = User.objects.order_by("username")
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]
    filterset_fields = ["role", "is_active"]
    search_fields = ["username", "first_name", "last_name"]

    def perform_create(self, serializer):
        user = serializer.save()
        record(self.request.user, "user.created", user, f"Created user {user.username} as {user.role}")

    def perform_update(self, serializer):
        user = serializer.save()
        record(self.request.user, "user.updated", user, f"Updated user {user.username}", role=user.role)

    def destroy(self, request, *args, **kwargs):
        # Users referenced by audit history can't be deleted; deactivate instead.
        user = self.get_object()
        user.is_active = False
        user.save(update_fields=["is_active"])
        record(request.user, "user.deactivated", user, f"Deactivated {user.username}")
        return Response(status=status.HTTP_204_NO_CONTENT)
