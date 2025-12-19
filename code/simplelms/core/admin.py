from django.contrib import admin
from .models import Course, CourseMember, CourseContent, Comment
from django.contrib.auth.models import User

class CourseAdmin(admin.ModelAdmin):
    # list_display: Field apa saja yang ditampilkan di daftar data
    list_display = ('name', 'teacher', 'price', 'created_at', 'updated_at')
    
    # search_fields: Field mana yang bisa dicari (searching)
    search_fields = ['name', 'teacher__username'] # Mencari berdasarkan nama kursus atau username pengajar
    
    # list_filter: Filter di sidebar (misalnya filter berdasarkan pengajar)
    list_filter = ['teacher']

# Register your models here.
admin.site.register(Course, CourseAdmin)
admin.site.register(CourseMember)
admin.site.register(CourseContent)
admin.site.register(Comment)