from django.urls import path
from . import views

urlpatterns = [
    path('', views.search_view, name='search'),
    path('pricing/', views.pricing_view, name='pricing'),
    path('activate-premium/', views.activate_premium, name='activate_premium'),
    path('tasks/', views.tasks_view, name='tasks'),
    path('tasks/<str:task_id>', views.task_detail_view, name='task_detail'),
    path('tasks/<str:task_id>/', views.task_detail_view), # Support both
    path('tasks/clear/', views.clear_history, name='clear_history'),
    path('export/', views.export_csv_view, name='export_csv'),
    path('create-order/', views.create_razorpay_order, name='create_order'),
    path('verify-payment/', views.verify_payment, name='verify_payment'),
    path('about/', views.about_view, name='about'),
]
