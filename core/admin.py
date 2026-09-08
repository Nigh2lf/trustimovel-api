from django.contrib import admin
from django.contrib.auth.models import Group as DjangoGroup
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Count
from .models import (
    Agency,
    AgencyExporter,
    AgencyExporterPlan,
    AssistantConversation,
    AssistantMessage,
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


class AssistantMessageInline(admin.TabularInline):
    """Itens da conversa com o Theo. É histórico: o admin só lê, não inclui nem apaga."""

    model = AssistantMessage
    extra = 0
    can_delete = False
    fields = ('created_at', 'role', 'content')
    readonly_fields = fields
    ordering = ('created_at',)

    def has_add_permission(self, request, obj=None):
        return False


class AssistantConversationAdmin(admin.ModelAdmin):
    """Conversas do Theo, uma por usuário e assunto, com as mensagens embaixo.

    Tudo é gravado pela API (/assistant/chat/); o admin serve para auditar. Excluir fica
    bloqueado porque a ação em massa apagaria de verdade, passando por cima do soft delete.
    """

    list_display = ('title', 'user', 'agency', 'message_count', 'updated_at', 'deleted_at')
    list_filter = ('agency',)
    search_fields = ('title', 'user__email', 'messages__content')
    readonly_fields = ('agency', 'user', 'title', 'created_at', 'updated_at', 'deleted_at')
    date_hierarchy = 'updated_at'
    inlines = [AssistantMessageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_message_count=Count('messages'))

    @admin.display(description='Mensagens', ordering='_message_count')
    def message_count(self, obj):
        return obj._message_count

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AssistantMessageAdmin(admin.ModelAdmin):
    """Todas as mensagens, para procurar um trecho sem saber em qual conversa está."""

    list_display = ('created_at', 'conversation', 'role', 'short_content')
    list_filter = ('role', 'conversation__agency')
    search_fields = ('content', 'conversation__title', 'conversation__user__email')
    readonly_fields = ('conversation', 'role', 'content', 'created_at')
    date_hierarchy = 'created_at'

    @admin.display(description='Conteúdo')
    def short_content(self, obj):
        return obj.content[:80]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
admin.site.register(AssistantConversation, AssistantConversationAdmin)
admin.site.register(AssistantMessage, AssistantMessageAdmin)
admin.site.unregister(DjangoGroup)
