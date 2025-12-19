from django.contrib import admin
from django.urls import path, include
from core import views as core_views
from core.apiv1 import apiv1 
from core.apiv2 import api_v2

urlpatterns = [
    path('', core_views.home, name='home'), 
    path('admin/', admin.site.urls),
    path('core/', include('core.urls')), 
    path('silk/', include('silk.urls', namespace='silk')),
    path('api/v1/', apiv1.urls),
    path('api/v2/', api_v2.urls),
]