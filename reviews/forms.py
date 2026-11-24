from django import forms

from .models import Review

RATING_CHOICES = [
    ("", "Choose a rating"),
    (5, "5 – Excellent"),
    (4, "4 – Good"),
    (3, "3 – Okay"),
    (2, "2 – Poor"),
    (1, "1 – Terrible"),
]


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        label="Rating",
        choices=RATING_CHOICES,
        coerce=int,
        empty_value=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    text = forms.CharField(
        label="Comment",
        required=False,
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Share your thoughts about this book (optional)",
            }
        ),
    )

    class Meta:
        model = Review
        fields = ("rating", "text")