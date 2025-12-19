from django.test import TestCase, Client
from django.contrib.auth.models import User
from .models import Course, CourseMember, CourseContent

# ==========================================
# 1. TEST DATABASE (MODELS)
# ==========================================
class CourseModelTest(TestCase):
    def setUp(self):
        self.teacher = User.objects.create(username='pak_guru')
        
        self.course = Course.objects.create(
            name="Belajar Docker Django",
            description="Materi pertemuan 10 dan 11",
            price=150000,
            teacher=self.teacher  
        )

    def test_create_course(self):
        """Tes apakah Course berhasil disimpan ke database"""
        course = Course.objects.get(name="Belajar Docker Django")
        self.assertEqual(course.price, 150000)
        self.assertEqual(course.teacher.username, 'pak_guru')
        expected_str = f"{course.name} : {course.price}"
        self.assertEqual(str(course), expected_str)

class CourseMemberTest(TestCase):
    def setUp(self):
        self.teacher = User.objects.create(username='guru1')
        self.student = User.objects.create(username='murid1')
        self.course = Course.objects.create(name="Matematika", price=50000, teacher=self.teacher)

    def test_add_member(self):
        member = CourseMember.objects.create(
            course_id=self.course,
            user_id=self.student,
            roles='std'
        )
        
        self.assertEqual(member.user_id.username, 'murid1')
        self.assertEqual(member.course_id.name, 'Matematika')

# ==========================================
# 2. TEST API V2 (Project Pertemuan 10)
# ==========================================
class CourseApiV2Test(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create(username='dosen_api')
        
        Course.objects.create(name="Python Dasar", price=100000, teacher=self.teacher)
        Course.objects.create(name="Python Lanjut", price=200000, teacher=self.teacher)

    def test_get_courses_api_v2(self):
        response = self.client.get('/api/v2/courses')
        
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn('items', data)  
        self.assertIn('total', data)    
        self.assertIn('per_page', data) 
        
        self.assertEqual(len(data['items']), 2)

    def test_filter_api_v2(self):
        response = self.client.get('/api/v2/courses?search=Lanjut')
        data = response.json()
        
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['name'], "Python Lanjut")