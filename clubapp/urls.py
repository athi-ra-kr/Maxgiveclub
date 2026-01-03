from django.urls import path
from . import views

urlpatterns = [
    # ... (Keep your admin paths the same) ...
    path('adminlogin/', views.adminlogin, name='adminlogin'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('project-value/', views.project_value_view, name='project_value'),
    path('logout/', views.logout_admin, name='logout_admin'),
    path("add-member/", views.add_member, name="add_member"),
    path("members/", views.list_members, name="list_members"),
    path("members/<int:pk>/edit/", views.edit_member, name="edit_member"),
    path("members/<int:pk>/delete/", views.delete_member, name="delete_member"),
    path("buy-pv/", views.buy_pv_list, name="buy_pv_list"),
    path("buy-pv/add/", views.buy_pv_add, name="buy_pv_add"),
    path("buy-pv/<int:pk>/edit/", views.buy_pv_edit, name="buy_pv_edit"),
    path("buy-pv/<int:pk>/delete/", views.buy_pv_delete, name="buy_pv_delete"),
    path("members-pv-overview/", views.member_pv_overview, name="member_pv_overview"),
    
    # --- Public / Member Paths ---
    path('', views.index, name='index'),
    path('memberlogin/', views.memberlogin, name='memberlogin'),
    path("member/dashboard/", views.member_dashboard, name="member_dashboard"),
    path("member/logout/", views.member_logout, name="member_logout"),
    
    # UPDATED: Now accepts an integer ID for specific certificates
    path("member/certificate/<int:pk>/", views.member_certificate, name="member_certificate"),


    path("dividend/",views.dividend_list, name="dividend_list"),
    path("dividend/add/",views.dividend_add, name="dividend_add"),
    path("dividend/edit/<int:pk>/",views.dividend_edit, name="dividend_edit"),
    path("dividend/delete/<int:pk>/",views.dividend_delete, name="dividend_delete"),







]

