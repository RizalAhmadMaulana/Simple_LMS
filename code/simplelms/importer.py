# code/simplelms/importer.py

import os
import csv
from django.db import connection 
from django.core.exceptions import ObjectDoesNotExist 

# --- SETUP DJANGO HARUS PALING ATAS ---
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simplelms.settings') 
import django
django.setup() 
# --- END SETUP ---

from django.contrib.auth.models import User
from core.models import Course, CourseMember 

# Path folder CSV di dalam kontainer
CSV_DIR = '/code/csv_data/'

# --- FUNGSI HELPER UNTUK RESET SEQUENCE ---
def reset_db_sequences():
    """Mengatur ulang penghitung ID otomatis PostgreSQL untuk User dan Course."""
    try:
        with connection.cursor() as cursor:
            # Reset User Sequence
            cursor.execute("SELECT setval('auth_user_id_seq', (SELECT MAX(id) FROM auth_user));")
            # Reset Course Sequence
            cursor.execute("SELECT setval('core_course_id_seq', (SELECT MAX(id) FROM core_course));")
        print("INFO: PostgreSQL sequences reset successfully.")
    except Exception as e:
        print(f"WARNING: Gagal reset sequence (lanjutkan jika DB bersih): {e}")
# ----------------------------------------------------------------------


# --- 1. IMPORT USER DATA (Memaksa PK) ---
print("--- 1. Importing User Data ---")
with open(os.path.join(CSV_DIR, 'user-data.csv'), mode='r') as csvfile:
    reader = csv.DictReader(csvfile)
    
    for row in reader:
        try:
            user_id_from_csv = int(row['id']) # Wajib ada kolom 'id' di CSV
        except (ValueError, KeyError):
            print(f"SKIP: User {row.get('username', 'Unknown')} missing 'id' or invalid value.")
            continue
            
        if not User.objects.filter(pk=user_id_from_csv).exists():
            
            # Gunakan .create() untuk memasukkan ID manual
            user = User.objects.create(
                id=user_id_from_csv, 
                username=row['username'],
                email=row['email'], 
                is_staff=True, 
                is_active=True,
            )
            # Hash password secara manual 
            user.set_password(row['password'])
            user.save() 
            print(f"Imported User: {row['username']} (PK: {user.pk})")

# Reset sequence setelah import User selesai
reset_db_sequences()


# --- 2. IMPORT COURSE DATA ---
print("\n--- 2. Importing Course Data ---")
with open(os.path.join(CSV_DIR, 'course-data.csv'), mode='r') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        if not Course.objects.filter(name=row['name']).exists():
            
            try:
                # Pencarian berdasarkan PK User
                teacher_user = User.objects.get(pk=int(row['teacher']))
            except (ObjectDoesNotExist, ValueError):
                print(f"ERROR: Teacher ID {row['teacher']} not found or invalid. Skipping course {row['name']}.")
                continue
            
            Course.objects.create(
                name=row['name'],
                description=row['description'],
                price=int(row['price']), 
                teacher=teacher_user
            )
            print(f"Imported Course: {row['name']}")


# --- 3. IMPORT MEMBER DATA (Koreksi Field Relasi) ---
print("\n--- 3. Importing Member Data ---")
with open(os.path.join(CSV_DIR, 'member-data.csv'), mode='r') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        
        course_id_str = row['course_id']
        user_id_str = row['user_id']

        try:
            course = Course.objects.get(pk=int(course_id_str))
            user = User.objects.get(pk=int(user_id_str))
            
        except ValueError:
            print(f"ERROR: ID Member tidak valid (Non-numeric): Course ID {course_id_str} or User ID {user_id_str}. Skipping.")
            continue
        except (Course.DoesNotExist, User.DoesNotExist):
            print(f"ERROR: Course ID {course_id_str} or User ID {user_id_str} not found in DB. Skipping member entry.")
            continue
            
        if not CourseMember.objects.filter(course_id=course, user_id=user).exists():
            CourseMember.objects.create(
                course_id=course,
                user_id=user,
                roles=row['roles']
            )
            print(f"Imported Member: User {user.username} to Course {course.name}")