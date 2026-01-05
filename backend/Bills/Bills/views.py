from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response


def hello_view(request):
    return HttpResponse("hello")
@api_view(['GET'])
def get_emails(request):
    return HttpResponse("hello")