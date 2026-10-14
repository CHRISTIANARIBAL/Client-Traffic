
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("api/traffic/", views.client_traffic, name="traffic"),
    path("admin-login/", views.admin_login, name="admin_login"),

    # NOC client management
    path("noc/clients/", views.client_list, name="client_list"),
    path("noc/clients/add/", views.client_add, name="client_add"),
    path("noc/clients/<int:client_id>/traffic/", views.client_traffic_detail, name="client_traffic_detail"),
    path("noc/api/clients/<int:client_id>/traffic/", views.client_traffic_history, name="client_traffic_history"),
    path("noc/clients/<int:client_id>/edit/", views.client_edit, name="client_edit"),
    path("noc/clients/<int:client_id>/delete/", views.client_delete, name="client_delete"),
]
