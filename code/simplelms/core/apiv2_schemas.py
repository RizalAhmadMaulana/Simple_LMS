from ninja import Schema

class CourseSchema(Schema):
    id: int
    name: str
    description: str
    price: int