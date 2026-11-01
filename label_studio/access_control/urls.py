from access_control import api
from django.urls import path

app_name = 'access_control'

urlpatterns = [
    path('api/access-control/groups/', api.AccessGroupListAPI.as_view(), name='access-group-list'),
    path('api/access-control/users/', api.UserAccessListAPI.as_view(), name='user-access-list'),
    path('api/access-control/users/<int:pk>/', api.UserAccessAPI.as_view(), name='user-access-detail'),
]
