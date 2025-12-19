from django.http import JsonResponse,HttpResponse
from django.contrib.auth.models import User
from django.db.models import Max, Min, Avg, Count
from .models import Course, CourseContent, CourseMember  
from django.core import serializers
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import render

def api_all_courses(request):
    courses = Course.objects.select_related('teacher').all()
    return render(request, 'all_courses.html', {'courses': courses})

def api_user_courses(request):
    members = CourseMember.objects.select_related('user_id', 'course_id').all()
    return render(request, 'user_courses.html', {'members': members})

def api_course_stats(request):
    stats = Course.objects.aggregate(
        total_courses=Count('id'),
        avg_price=Avg('price'),
        max_price=Max('price'),
        min_price=Min('price')
    )
    
    if stats['avg_price'] is not None:
        stats['avg_price'] = int(stats['avg_price'])

    return render(request, 'stats_courses.html', {'stats': stats})

def api_member_stats(request):
    total_members = CourseMember.objects.count()
    role_stats = CourseMember.objects.values('roles').annotate(total=Count('id'))
    
    return render(request, 'stats_members.html', {
        'total_members': total_members,
        'role_stats': role_stats
    })

def index_courses(request):
    return render(request, 'courses.html')

def index_users(request):
    return render(request, 'users.html')

def create_test_user(request):
    user = User.objects.create_user(
        username="rizal",
        email="rizalram100@gmail.com",
        password="rizal_2004",
    )
    return JsonResponse({"id": user.id, "username": user.username})

def create_course_from_query(request):
    row = {
        "name": request.GET.get("name", "Nama Default"),
        "description": request.GET.get("description", "-"),
        "price": int(request.GET.get("price", 10000)),
    }

    teacher = User.objects.get(pk=1)
    course = Course.objects.create(
        name=row["name"],
        description=row["description"],
        price=row["price"],
        teacher=teacher,
    )
    return JsonResponse({"id": course.id, "name": course.name})

def allCourse(request):
    allCourse = Course.objects.all()
    result = []
    for course in allCourse:
        record = {
            'id': course.id, 
            'name': course.name,
            'description': course.description,
            'price': course.price,
            'teacher': {
                'id': course.teacher.id,
                'username': course.teacher.username,
                'email': course.teacher.email,
                'fullName': f"{course.teacher.first_name} {course.teacher.last_name}"
            }
        }
        result.append(record)
    return JsonResponse(result, safe=False)

def userCourses(request):
    user = User.objects.get(pk=3)
    courses = Course.objects.filter(teacher=user.id)
    
    course_data = []
    for course in courses:
        record = {
            'id': course.id, 
            'name': course.name,
            'description': course.description, 
            'price': course.price
        }
        course_data.append(record)
        
    result = {
        'id': user.id, 
        'username': user.username, 
        'email': user.email,
        'fullName': f"{user.first_name} {user.last_name}",
        'courses': course_data
    }
    
    return JsonResponse(result, safe=False)

def courseStat(request):
    courses = Course.objects.all()
    stats = courses.aggregate(max_price=Max('price'),
                              min_price=Min('price'),
                              avg_price=Avg('price'))
    
    cheapest = Course.objects.filter(price=stats['min_price'])
    expensive = Course.objects.filter(price=stats['max_price'])
    
    popular = Course.objects.annotate(member_count=Count('coursemember')) \
        .order_by('-member_count')[:5]
        
    unpopular = Course.objects.annotate(member_count=Count('coursemember')) \
        .order_by('member_count')[:5]
    
    result = {
        'course_count': len(courses), 
        'courses': stats,
        'cheapest': serializers.serialize('python', cheapest),
        'expensive': serializers.serialize('python', expensive),
        'popular': serializers.serialize('python', popular),
        'unpopular': serializers.serialize('python', unpopular)
    }
    
    return JsonResponse(result, safe=False)

def courseDetail(request, course_id):
    course = Course.objects.annotate(
        member_count=Count('coursemember'),
        content_count=Count('coursecontent'),
        comment_count=Count('coursecontent__comment')
    ).get(pk=course_id)

    contents = CourseContent.objects.filter(course_id=course.id) \
        .annotate(count_comment=Count('comment')) \
        .order_by('-count_comment')[:3]

    result = {
        'name': course.name,
        'description': course.description,
        'price': course.price,
        'member_count': course.member_count,
        'content_count': course.content_count,
        'teacher': {
            'username': course.teacher.username,
            'email': course.teacher.email,
            'fullname': f"{course.teacher.first_name} {course.teacher.last_name}"
        },
        'comment_stat': {
            'comment_count': course.comment_count,
            'most_comment': [
                {
                    'name': content.name, 
                    'comment_count': content.count_comment
                } 
                for content in contents
            ],
        },
    }
    return JsonResponse(result)

def courseMemberStat(request):
    courses = Course.objects.filter(description__contains='python') \
        .annotate(member_num=Count('coursemember'))
    
    course_data = []
    for course in courses:
        record = {'id': course.id, 'name': course.name, 'price': course.price,
                  'member_count': course.member_num}
        course_data.append(record)
        
    result = {'data_count': len(course_data), 'data': course_data}
    return JsonResponse(result)

def home(request):
    courses = Course.objects.all().select_related('teacher') \
        .annotate(member_count=Count('coursemember__user_id'))
    
    total_users = User.objects.filter(is_superuser=False).count()
    total_courses = Course.objects.count()
    total_members = CourseMember.objects.count()
    total_content = CourseContent.objects.count()
    
    context = {
        'title': 'SimpleLMS - Platform Belajar Masa Kini',
        'courses': courses,
        'stats': {
            'users': total_users,
            'courses': total_courses,
            'members': total_members,
            'content': total_content,
        }
    }
    
    return render(request, 'index.html', context)