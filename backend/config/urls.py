from django.urls import include, path

urlpatterns = [
    path("api/", include("trips.api.urls")),
]

handler400 = "trips.errors.bad_request_view"
handler403 = "trips.errors.forbidden_view"
handler404 = "trips.errors.not_found_view"
handler500 = "trips.errors.server_error_view"
