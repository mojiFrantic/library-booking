from captcha.fields import CaptchaField
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class BootstrapMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "captcha":
                field.widget.attrs.setdefault("class", "form-control")


class RegisterForm(BootstrapMixin, UserCreationForm):
    email = forms.EmailField(label="Email")
    phone = forms.CharField(label="Phone", max_length=15, required=False)
    captcha = CaptchaField(label="Security code")

    class Meta:
        model = User
        fields = ("username", "email", "phone")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email


class LoginForm(BootstrapMixin, AuthenticationForm):
    captcha = CaptchaField(label="Security code")