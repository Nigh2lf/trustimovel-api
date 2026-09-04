from django.contrib import admin
from django.contrib.auth.models import Group as DjangoGroup
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    Agency,
    AgencyExporter,
    AgencyExporterPlan,
    Broker,
    City,
    Client,
    CompanySection,
    Condominium,
    CondominiumPhoto,
    Country,
    Exporter,
    ExporterPlan,
    Feature,
    Fee,
    Neighborhood,
    Owner,
    Plan,
    Property,
    PropertyExporter,
    PropertyFee,
    PropertyPhoto,
    PropertyPrice,
    PropertyType,
    SiteBanner,
    State,
    User,
)

admin.site.site_header = 'Projeto Admin'


class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'is_admin', 'is_active',)
    list_filter = ('is_admin', 'is_active',)
    fieldsets = (
        (None, {'fields': ('email',
                            'password',
                            'agency',
                            'profile_image',
                            'name',
                            'is_active',)}),
        ('Permissions', {'fields': ('is_admin', 'type',)}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2',)}
         ),
    )
    search_fields = ('email',)
    ordering = ('email',)
    filter_horizontal = ()


class PropertyPhotoInline(admin.TabularInline):
    model = PropertyPhoto
    extra = 1


class PropertyPriceInline(admin.TabularInline):
    model = PropertyPrice
    extra = 1


class PropertyFeeInline(admin.TabularInline):
    model = PropertyFee
    extra = 1


class PropertyExporterInline(admin.TabularInline):
    model = PropertyExporter
    extra = 1


class PropertyAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'agency', 'type', 'neighborhood', 'featured', 'is_active', 'deleted_at')
    list_filter = ('agency', 'type', 'featured', 'is_active')
    search_fields = ('name', 'address')
    filter_horizontal = ('features',)
    inlines = [PropertyPhotoInline, PropertyPriceInline, PropertyFeeInline, PropertyExporterInline]


class AgencyAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'plan', 'is_active', 'deleted_at')
    search_fields = ('name', 'email')


class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'property_limit', 'photo_limit', 'deleted_at')
    search_fields = ('name',)


class AgencyExporterPlanInline(admin.TabularInline):
    model = AgencyExporterPlan
    extra = 1


class AgencyExporterAdmin(admin.ModelAdmin):
    list_display = ('agency', 'exporter')
    list_filter = ('agency', 'exporter')
    inlines = [AgencyExporterPlanInline]


class PropertyTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'deleted_at')
    search_fields = ('name',)


class CondominiumPhotoInline(admin.TabularInline):
    model = CondominiumPhoto
    extra = 1


class CondominiumAdmin(admin.ModelAdmin):
    list_display = ('name', 'agency', 'neighborhood', 'deleted_at')
    list_filter = ('agency',)
    search_fields = ('name',)
    filter_horizontal = ('features',)
    inlines = [CondominiumPhotoInline]


class CountryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'deleted_at')
    search_fields = ('name', 'code')


class StateAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation', 'country', 'deleted_at')
    list_filter = ('country',)
    search_fields = ('name', 'abbreviation')


class CityAdmin(admin.ModelAdmin):
    list_display = ('name', 'state', 'ibge_code', 'deleted_at')
    list_filter = ('state',)
    search_fields = ('name', 'ibge_code')


class NeighborhoodAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'deleted_at')
    list_filter = ('city',)
    search_fields = ('name',)


class BrokerAdmin(admin.ModelAdmin):
    list_display = ('name', 'agency', 'phone', 'email', 'deleted_at')
    list_filter = ('agency',)
    search_fields = ('name', 'email', 'phone')


class OwnerAdmin(admin.ModelAdmin):
    list_display = ('name', 'agency', 'phone', 'email', 'deleted_at')
    list_filter = ('agency',)
    search_fields = ('name', 'email', 'phone')


class ClientAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'agency', 'type', 'phone', 'email', 'is_active', 'deleted_at')
    list_filter = ('agency', 'type', 'is_active')
    search_fields = ('code', 'name', 'email', 'phone', 'document')


class CompanySectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'agency', 'deleted_at')
    list_filter = ('agency',)
    search_fields = ('title', 'text')


class SiteBannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'agency', 'link', 'is_active', 'deleted_at')
    list_filter = ('agency', 'is_active')
    search_fields = ('title', 'link')


class FeatureAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'deleted_at')
    list_filter = ('type',)
    search_fields = ('name',)


class FeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'deleted_at')
    search_fields = ('name',)


class ExporterPlanInline(admin.TabularInline):
    model = ExporterPlan
    extra = 1


class ExporterAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'deleted_at')
    search_fields = ('name',)
    inlines = [ExporterPlanInline]


admin.site.register(User, UserAdmin)
admin.site.register(Broker, BrokerAdmin)
admin.site.register(Owner, OwnerAdmin)
admin.site.register(Client, ClientAdmin)
admin.site.register(CompanySection, CompanySectionAdmin)
admin.site.register(SiteBanner, SiteBannerAdmin)
admin.site.register(Feature, FeatureAdmin)
admin.site.register(Fee, FeeAdmin)
admin.site.register(Exporter, ExporterAdmin)
admin.site.register(Agency, AgencyAdmin)
admin.site.register(Plan, PlanAdmin)
admin.site.register(AgencyExporter, AgencyExporterAdmin)
admin.site.register(Country, CountryAdmin)
admin.site.register(State, StateAdmin)
admin.site.register(City, CityAdmin)
admin.site.register(Neighborhood, NeighborhoodAdmin)
admin.site.register(PropertyType, PropertyTypeAdmin)
admin.site.register(Condominium, CondominiumAdmin)
admin.site.register(Property, PropertyAdmin)
admin.site.unregister(DjangoGroup)
