# members/models.py
from django.db import models
import string
import random


def generate_random_password(length=8):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


class Member(models.Model):
    member_code = models.CharField(max_length=10, unique=True, blank=True)
    full_name = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True)

    # ✅ Aadhaar removed, using address instead
    address = models.CharField(max_length=255, blank=True)

    # Plain-text password (as per your design)
    password = models.CharField(max_length=128, blank=True)

    join_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member_code} - {self.full_name}"

    def save(self, *args, **kwargs):
        # Auto-generate member_code only on create
        if not self.member_code:
            last = Member.objects.order_by('-id').first()
            next_number = 1 if not last else last.id + 1
            self.member_code = f"M{next_number:04d}"  # M0001, M0002, ...

        # Auto-generate password only on create
        if not self.password:
            self.password = generate_random_password(8)

        super().save(*args, **kwargs)


# models.py
from django.db import models
from django.utils import timezone

# import Member above or define it in the same file
# from .member_models import Member   # example if separated


def get_pv_value_for_year(target_year: int, base_year: int = 2026, base_value: float = 100.0) -> float:
    """
    PV value per 1 PV for a given year, based on your table:

      2026: 100 (no increase)
      2027: +8%
      2028: +9%
      2029: +10%
      2030: +11%
      ...
      2036: +17%

    Pattern:
      - Start with 100 in base_year
      - For each year after that, multiply by (1 + yearly_rate)
      - yearly_rate for offset i (1st year after base) = (7 + i) %

    This reproduces exactly your screenshot values.
    """
    value = float(base_value)

    if target_year <= base_year:
        return round(value, 2)

    years_after = target_year - base_year
    for i in range(1, years_after + 1):
        yearly_rate = (7 + i) / 100.0  # 1 -> 8%, 2 -> 9%, ...
        value *= (1 + yearly_rate)

    return round(value, 2)


class PVTransaction(models.Model):
    member = models.ForeignKey("Member", on_delete=models.CASCADE, related_name="pv_transactions")
    pv_units = models.PositiveIntegerField()
    purchase_date = models.DateTimeField(auto_now_add=True)
    # note field removed

    def __str__(self):
        return f"{self.member.member_code} - {self.pv_units} PV"

    @property
    def current_value_per_pv(self) -> float:
        """
        Value of 1 PV in the *current year* using the growth table.
        """
        year = timezone.now().year
        return get_pv_value_for_year(year)

    @property
    def current_total_value(self) -> float:
        """
        Total value of this transaction (all PV units) in the *current year*.
        """
        return round(self.pv_units * self.current_value_per_pv, 2)
