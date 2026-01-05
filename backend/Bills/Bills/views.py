from django.http import HttpResponse

def hello_view(request):
    return HttpResponse("hello")

def get_emails(request):
    return HttpResponse("hello")