from django.contrib import admin
from .models import Member, PVTransaction


from django.contrib import admin
from .models import Member


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = (
        'member_code',
        'full_name',
        'email',
        'phone_number',
        'address',
        'password',
        'join_date',
    )

    search_fields = (
        'member_code',
        'full_name',
        'email',
        'phone_number',
        'address',
    )

    list_filter = ('join_date',)

    readonly_fields = ('member_code', 'password', 'join_date')



@admin.register(PVTransaction)
class PVTransactionAdmin(admin.ModelAdmin):
    # no 'note' here anymore
    list_display = ("member", "pv_units", "purchase_date", "current_value_per_pv", "current_total_value")
    search_fields = ("member__member_code", "member__full_name")
    list_filter = ("purchase_date",)
