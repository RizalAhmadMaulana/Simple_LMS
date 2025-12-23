from django.test import TestCase, Client 
from django.contrib.auth.models import User
from .models import Course, CourseMember, CourseContent, Comment
import json
from django.test import override_settings

@override_settings(TESTING=True)
class SimpleLMSCompleteTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(username='dosen_uji', password='password123')
        self.student = User.objects.create_user(username='murid_uji', password='password123')
        
        self.course = Course.objects.create(name="Django Advanced", price=500000, teacher=self.teacher)
        self.content = CourseContent.objects.create(course_id=self.course, name="Video Tutorial 1")

        # Login menggunakan endpoint manual yang baru kita buat
        response = self.client.post(
            '/api/v2/auth/sign-in',
            data=json.dumps({"username": "murid_uji", "password": "password123"}),
            content_type="application/json"
        )
        
        # Pastikan login sukses (200 OK) sebelum lanjut
        self.assertEqual(response.status_code, 200, f"Login gagal! Response: {response.content}")
        self.token = response.json().get('access')
        
        # Header Auth Standar Django Client
        self.auth_headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def test_get_courses_public(self):
        response = self.client.get('/api/v2/courses')
        self.assertEqual(response.status_code, 200)

    def test_enroll_unauthorized(self):
        response = self.client.post(f'/api/v2/course/{self.course.id}/enroll/')
        self.assertEqual(response.status_code, 401)

    def test_enroll_success(self):
        response = self.client.post(
            f'/api/v2/course/{self.course.id}/enroll/', 
            **self.auth_headers
        )
        self.assertEqual(response.status_code, 200)

    def test_enroll_duplicate(self):
        CourseMember.objects.create(user_id=self.student, course_id=self.course)
        response = self.client.post(
            f'/api/v2/course/{self.course.id}/enroll/', 
            **self.auth_headers
        )
        self.assertEqual(response.status_code, 400)

    def test_post_comment_success(self):
        CourseMember.objects.create(user_id=self.student, course_id=self.course)
        data = {"comment": "Mantap", "content_id": self.content.id}
        response = self.client.post(
            '/api/v2/comments/', 
            data=json.dumps(data), 
            content_type="application/json", 
            **self.auth_headers
        )
        self.assertEqual(response.status_code, 200)

    def test_pagination_structure(self):
        response = self.client.get('/api/v2/courses')
        self.assertIn('items', response.json())