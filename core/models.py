import datetime
import uuid
from pathlib import Path

from django.db import models, transaction
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.utils.text import slugify
from django.utils import timezone

from core.resources import RESOURCE_CHOICES, AccessLevel


def update_last_login(sender, user, **kwargs):
    """
    A signal receiver which updates the last_login date for
    the user logging in.
    """
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])


class Country(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=80, unique=True)
    code       = models.CharField(max_length=3, unique=True, help_text='Sigla ISO, ex.: BRA')
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'País'
        verbose_name_plural = 'Países'
        ordering = ('name',)

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class State(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    country      = models.ForeignKey(Country, on_delete=models.PROTECT, related_name='states')
    name         = models.CharField(max_length=80)
    abbreviation = models.CharField(max_length=4, help_text='UF, ex.: RJ')
    deleted_at   = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Estado'
        verbose_name_plural = 'Estados'
        ordering = ('name',)
        unique_together = ('country', 'abbreviation')

    def __str__(self):
        return f'{self.name}/{self.abbreviation}'

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class City(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state      = models.ForeignKey(State, on_delete=models.PROTECT, related_name='cities')
    name       = models.CharField(max_length=120)
    ibge_code  = models.CharField(max_length=7, unique=True, help_text='Código IBGE do município, ex.: 3304557')
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cidade'
        verbose_name_plural = 'Cidades'
        ordering = ('name',)
        unique_together = ('state', 'name')

    def __str__(self):
        return f'{self.name} - {self.state.abbreviation}'

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Neighborhood(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    city       = models.ForeignKey(City, on_delete=models.PROTECT, related_name='neighborhoods')
    name       = models.CharField(max_length=120)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Bairro'
        verbose_name_plural = 'Bairros'
        ordering = ('name',)
        unique_together = ('city', 'name')

    def __str__(self):
        return f'{self.name} - {self.city.name}'

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class PropertyType(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=100, unique=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tipo de imóvel'
        verbose_name_plural = 'Tipos de imóvel'
        ordering = ('name',)

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Plan(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name           = models.CharField(max_length=100, unique=True)
    property_limit = models.PositiveIntegerField(null=True, blank=True, help_text='Vazio = imóveis ilimitados')
    photo_limit    = models.PositiveIntegerField(null=True, blank=True, help_text='Vazio = fotos ilimitadas')
    deleted_at     = models.DateTimeField(null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Plano'
        verbose_name_plural = 'Planos'
        ordering = ('name',)

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Agency(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=100)
    plan       = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.PROTECT, related_name='agencies')
    slug       = models.SlugField(max_length=100, unique=True, blank=True, help_text='Usado na pasta de arquivos da imobiliária')
    logo       = models.ImageField(upload_to='agency_logos', null=True, blank=True)
    site       = models.URLField(max_length=200, blank=True)
    phone      = models.CharField(max_length=20, blank=True)
    email      = models.EmailField(max_length=255, blank=True)
    is_active  = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Imobiliária'
        verbose_name_plural = 'Imobiliárias'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.is_active = False
        self.deleted_at = timezone.now()
        self.save()


class UserManager(BaseUserManager):

    def create_user(self, email, password=None):
        if not email:
            raise ValueError('Informe o e-mail do usuário.')

        user = self.model(
            email=email,
        )

        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password):
        user = self.create_user(
            email,
            password=password,
        )

        user.is_admin = True
        user.save(using=self._db)

        return user


class User(AbstractBaseUser):
    class Type(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrador'
        USER = 'USER', 'Usuário'
        BROKER = 'BROKER', 'Corretor'

    class QueuePresence(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Disponível'
        PAUSED = 'PAUSED', 'Pausado'
        OFF = 'OFF', 'Fora da fila'

    id                     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency                 = models.ForeignKey(Agency, null=True, blank=True, on_delete=models.PROTECT, related_name='users')
    profile_image          = models.ImageField(upload_to='profile_images', null=True, blank=True)
    email                  = models.EmailField(max_length=255, null=False, blank=False, unique=True)
    name                   = models.CharField(max_length=255, null=True, blank=True)
    is_admin               = models.BooleanField(default=False)
    is_active              = models.BooleanField(default=True)
    deleted_at             = models.DateTimeField(null=True, blank=True)
    deleted_by             = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='deleted_users')
    created_at             = models.DateTimeField(auto_now_add=True)
    updated_at             = models.DateTimeField(auto_now=True)
    type                   = models.CharField(max_length=10, choices=Type.choices, default=Type.USER)
    forgot_password_hash   = models.CharField(max_length=255, null=True, blank=True)
    forgot_password_expire = models.DateTimeField(null=True, blank=True)
    team                   = models.CharField(max_length=100, blank=True, help_text='Equipe do corretor')
    in_queue               = models.BooleanField(default=True, help_text='Corretor participa da roleta da fila de atendimento')
    queue_presence         = models.CharField(max_length=10, choices=QueuePresence.choices, default=QueuePresence.AVAILABLE)
    queue_pause_reason     = models.CharField(max_length=150, blank=True)
    queue_order            = models.PositiveIntegerField(default=0, help_text='Posição na roleta; quem recebe um lead vai para o final')
    queue_skips            = models.PositiveSmallIntegerField(default=0, help_text='Ofertas perdidas seguidas; zera ao aceitar')

    objects = UserManager()

    USERNAME_FIELD = 'email'

    def get_short_name(self):
        return self.email

    def __str__(self):
        return self.email

    def has_perm(self, perm, obj=None):
        return True

    def has_module_perms(self, app_label):
        return True

    @property
    def is_staff(self):
        return self.type == 'ADMIN'

    @property
    def permission_map(self):
        """Mapa {recurso: nível} do usuário, resolvido uma vez por instância.

        Cacheado porque a checagem de permissão roda a cada requisição e o alternativo
        seria uma consulta por recurso consultado.
        """
        if not hasattr(self, '_permission_map'):
            self._permission_map = {
                permission.resource: permission.level
                for permission in self.permissions.all()
            }

        return self._permission_map

    def level_for(self, resource):
        """Nível do usuário no recurso. ADMIN da plataforma passa por cima de tudo."""
        if self.type == User.Type.ADMIN:
            return AccessLevel.FULL

        return self.permission_map.get(resource, AccessLevel.NO_ACCESS)

    def can(self, resource, level):
        return self.level_for(resource) >= level

    def delete(self, deleted_by=None, *args, **kwargs):
        self.is_active = False
        self.deleted_at = timezone.now()
        if deleted_by:
            self.deleted_by = deleted_by
        self.save()


class Condominium(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency       = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='condominiums')
    neighborhood = models.ForeignKey(Neighborhood, null=True, blank=True, on_delete=models.PROTECT, related_name='condominiums')
    features     = models.ManyToManyField('Feature', blank=True, related_name='condominiums')
    name         = models.CharField(max_length=120)
    description  = models.TextField(blank=True)
    address      = models.CharField(max_length=255, blank=True)
    deleted_at   = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Condomínio'
        verbose_name_plural = 'Condomínios'

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Broker(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency     = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='brokers')
    name       = models.CharField(max_length=150)
    email      = models.EmailField(max_length=255, blank=True)
    phone      = models.CharField(max_length=20, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Captador'
        verbose_name_plural = 'Captadores'
        ordering = ('name',)
        unique_together = ('agency', 'name')

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Owner(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency         = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='owners')
    neighborhood   = models.ForeignKey(Neighborhood, null=True, blank=True, on_delete=models.PROTECT, related_name='owners')
    name           = models.CharField(max_length=150)
    spouse         = models.CharField(max_length=150, blank=True, help_text='Nome do cônjuge')
    email          = models.EmailField(max_length=255, blank=True)
    phone          = models.CharField(max_length=20, blank=True)
    mobile         = models.CharField(max_length=20, blank=True)
    business_phone = models.CharField(max_length=20, blank=True)
    document       = models.CharField(max_length=20, blank=True, help_text='CPF ou CNPJ')
    birth_date     = models.DateField(null=True, blank=True)
    address        = models.CharField(max_length=255, blank=True)
    number         = models.CharField(max_length=10, blank=True)
    complement     = models.CharField(max_length=60, blank=True)
    zip_code       = models.CharField(max_length=10, blank=True)
    notes          = models.TextField(blank=True)
    deleted_at     = models.DateTimeField(null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Proprietário'
        verbose_name_plural = 'Proprietários'
        ordering = ('name',)
        unique_together = ('agency', 'name')

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Client(models.Model):
    class Type(models.TextChoices):
        BUYER = 'BUYER', 'Comprador'
        SELLER = 'SELLER', 'Vendedor'
        TENANT = 'TENANT', 'Locatário'
        LANDLORD = 'LANDLORD', 'Locador'

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency       = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='clients')
    neighborhood = models.ForeignKey(Neighborhood, null=True, blank=True, on_delete=models.PROTECT, related_name='clients')
    code         = models.CharField(max_length=20, blank=True, help_text='Código do cliente dentro da imobiliária, aceita letras e números')
    name         = models.CharField(max_length=150)
    email        = models.EmailField(max_length=255, blank=True)
    phone        = models.CharField(max_length=20, blank=True)
    document     = models.CharField(max_length=20, blank=True, help_text='CPF ou CNPJ')
    type         = models.CharField(max_length=10, choices=Type.choices, default=Type.BUYER)
    birth_date   = models.DateField(null=True, blank=True)
    occupation   = models.CharField(max_length=100, blank=True)
    address      = models.CharField(max_length=255, blank=True)
    number       = models.CharField(max_length=10, blank=True)
    complement   = models.CharField(max_length=60, blank=True)
    zip_code     = models.CharField(max_length=10, blank=True)
    notes        = models.TextField(blank=True)
    is_active    = models.BooleanField(default=True)
    deleted_at   = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ('name',)
        unique_together = ('agency', 'code')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            with transaction.atomic():
                self.code = self._next_code()
                return super().save(*args, **kwargs)

        super().save(*args, **kwargs)

    def _next_code(self):
        # Trava a imobiliária para dois cadastros simultâneos não tirarem o mesmo código.
        Agency.objects.select_for_update().filter(pk=self.agency_id).first()
        # O código aceita letras, então a numeração automática olha só os puramente numéricos.
        numeric_codes = Client.objects.filter(
            agency_id=self.agency_id, code__regex=r'^[0-9]+$'
        ).values_list('code', flat=True)

        return str(max((int(code) for code in numeric_codes), default=0) + 1)

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


def site_image_upload_to(instance, filename):
    # Nome gerado aqui: o cliente não escolhe caminho nem sobrescreve arquivo de outra imobiliária.
    extension = Path(filename).suffix.lower()

    return (
        f'site/{instance.agency.slug}/'
        f'{instance._meta.model_name}-{uuid.uuid4().hex}{extension}'
    )


class CompanySection(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency     = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='company_sections')
    title      = models.CharField(max_length=100)
    text       = models.TextField(blank=True)
    image      = models.ImageField(upload_to=site_image_upload_to, null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Seção da empresa'
        verbose_name_plural = 'Seções da empresa'
        ordering = ('title',)

    def __str__(self):
        return self.title

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class SiteBanner(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency     = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='site_banners')
    title      = models.CharField(max_length=100)
    link       = models.URLField(max_length=200, blank=True, help_text='Destino do banner no site')
    image      = models.ImageField(upload_to=site_image_upload_to)
    is_active  = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Banner do site'
        verbose_name_plural = 'Banners do site'
        ordering = ('title',)

    def __str__(self):
        return self.title

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class BlogCategory(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency     = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='blog_categories')
    name       = models.CharField(max_length=100)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Categoria do blog'
        verbose_name_plural = 'Categorias do blog'
        ordering = ('name',)

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class BlogPost(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Rascunho'
        PUBLISHED = 'PUBLISHED', 'Publicado'

    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency           = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='blog_posts')
    category         = models.ForeignKey(BlogCategory, on_delete=models.PROTECT, related_name='posts')
    title            = models.CharField(max_length=160)
    slug             = models.SlugField(max_length=180, blank=True, help_text='Endereço da matéria no site')
    published_at     = models.DateField(default=timezone.localdate)
    image            = models.ImageField(upload_to=site_image_upload_to, null=True, blank=True)
    youtube_url      = models.URLField(max_length=200, blank=True)
    description      = models.TextField(blank=True)
    meta_title       = models.CharField(max_length=60, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)
    tags             = models.JSONField(default=list, blank=True)
    status           = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    deleted_at       = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Matéria do blog'
        verbose_name_plural = 'Matérias do blog'
        ordering = ('-published_at', '-created_at')
        # O endereço é único dentro do site de cada imobiliária, não do sistema inteiro.
        unique_together = ('agency', 'slug')

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:180]

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Feature(models.Model):
    class Type(models.TextChoices):
        PROPERTY = 'PROPERTY', 'Imóvel'
        CONDOMINIUM = 'CONDOMINIUM', 'Condomínio'

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=120)
    type       = models.CharField(max_length=20, choices=Type.choices, default=Type.PROPERTY)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Infraestrutura'
        verbose_name_plural = 'Infraestruturas'
        ordering = ('name',)
        unique_together = ('name', 'type')

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Fee(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=120, unique=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Taxa'
        verbose_name_plural = 'Taxas'
        ordering = ('name',)

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Exporter(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=120, unique=True)
    slug       = models.SlugField(max_length=120, unique=True, blank=True, help_text='Identifica o portal na URL de exportação')
    is_active  = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Exportador'
        verbose_name_plural = 'Exportadores'
        ordering = ('name',)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.is_active = False
        self.deleted_at = timezone.now()
        self.save()


class ExporterPlan(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exporter   = models.ForeignKey(Exporter, on_delete=models.CASCADE, related_name='plans')
    name       = models.CharField(max_length=60)
    position   = models.PositiveSmallIntegerField(default=0, help_text='Ordem do plano na tela')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Plano do exportador'
        verbose_name_plural = 'Planos do exportador'
        ordering = ('position', 'name')
        unique_together = ('exporter', 'name')

    def __str__(self):
        return f'{self.exporter.name} - {self.name}'


class AgencyExporter(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency     = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='agency_exporters')
    exporter   = models.ForeignKey(Exporter, on_delete=models.PROTECT, related_name='agency_exporters')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Exportador da imobiliária'
        verbose_name_plural = 'Exportadores da imobiliária'
        # Configuração sem exclusão lógica: remover o portal apaga a linha e recriar reativa.
        unique_together = ('agency', 'exporter')

    def __str__(self):
        return f'{self.agency.name} - {self.exporter.name}'


class AgencyExporterPlan(models.Model):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency_exporter = models.ForeignKey(AgencyExporter, on_delete=models.CASCADE, related_name='plans')
    plan            = models.ForeignKey(ExporterPlan, on_delete=models.CASCADE, related_name='agency_plans')
    limit           = models.PositiveIntegerField(default=0, help_text='Zero = nenhum imóvel neste plano')
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Limite de plano do exportador'
        verbose_name_plural = 'Limites de plano do exportador'
        ordering = ('plan__position', 'plan__name')
        unique_together = ('agency_exporter', 'plan')

    def __str__(self):
        return f'{self.plan.name}: {self.limit}'


class Property(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency         = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='properties')
    code           = models.CharField(max_length=20, blank=True, help_text='Código do imóvel dentro da imobiliária, aceita letras e números')
    type           = models.ForeignKey(PropertyType, null=True, blank=True, on_delete=models.PROTECT, related_name='properties')
    condominium    = models.ForeignKey(Condominium, null=True, blank=True, on_delete=models.PROTECT, related_name='properties')
    neighborhood   = models.ForeignKey(Neighborhood, null=True, blank=True, on_delete=models.PROTECT, related_name='properties')
    broker         = models.ForeignKey(Broker, null=True, blank=True, on_delete=models.PROTECT, related_name='properties')
    owner          = models.ForeignKey(Owner, null=True, blank=True, on_delete=models.PROTECT, related_name='properties')
    features       = models.ManyToManyField(Feature, blank=True, related_name='properties')
    name           = models.CharField(max_length=255, blank=True, help_text='Montado a partir do tipo e do bairro quando não informado')
    description    = models.TextField(blank=True)
    address        = models.CharField(max_length=255, blank=True)
    number         = models.CharField(max_length=10, blank=True)
    complement     = models.CharField(max_length=60, blank=True)
    zip_code       = models.CharField(max_length=10, blank=True)
    region         = models.CharField(max_length=80, blank=True)
    owner_name     = models.CharField(max_length=150, blank=True)
    local_contact  = models.CharField(max_length=150, blank=True, help_text='Contato no local do imóvel')
    contact_phone  = models.CharField(max_length=20, blank=True)
    area           = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text='Área total em m²')
    built_area     = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text='Área construída em m²')
    bedrooms       = models.PositiveSmallIntegerField(default=0)
    suites         = models.PositiveSmallIntegerField(default=0)
    bathrooms      = models.PositiveSmallIntegerField(default=0)
    living_rooms   = models.PositiveSmallIntegerField(default=0)
    parking_spaces = models.PositiveSmallIntegerField(default=0)
    guests         = models.PositiveSmallIntegerField(default=0)
    video_url      = models.URLField(max_length=255, blank=True, help_text='Vídeo do imóvel no YouTube')
    maps_url       = models.URLField(max_length=500, blank=True, help_text='Localização no Google Maps')
    visit_notes    = models.TextField(blank=True, help_text='Observações sobre visitas')
    document_notes = models.TextField(blank=True, help_text='Observações sobre a documentação')
    is_active      = models.BooleanField(default=True)
    featured       = models.BooleanField(default=False)
    exclusive      = models.BooleanField(default=False)
    reserved       = models.BooleanField(default=False)
    under_construction = models.BooleanField(default=False)
    opportunity    = models.BooleanField(default=False)
    has_leasehold  = models.BooleanField(default=False, help_text='Imóvel com laudêmio')
    on_site        = models.BooleanField(default=False, help_text='Publicado no site da imobiliária')
    show_prices    = models.BooleanField(default=True)
    accepts_trade  = models.BooleanField(default=False)
    trade_conditions = models.TextField(blank=True)
    views_count    = models.PositiveIntegerField(default=0)
    deleted_at     = models.DateTimeField(null=True, blank=True)
    deleted_by     = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='deleted_properties')
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Imóvel'
        verbose_name_plural = 'Imóveis'
        unique_together = ('agency', 'code')

    def __str__(self):
        return f'{self.code} - {self.name}'

    def save(self, *args, **kwargs):
        if not self.code:
            with transaction.atomic():
                self.code = self._next_code()
                self.name = self.name or self._build_name()
                return super().save(*args, **kwargs)

        self.name = self.name or self._build_name()

        super().save(*args, **kwargs)

    def _build_name(self):
        # O cadastro não pede nome: o imóvel se identifica pelo tipo e pelo bairro.
        type_name = self.type.name if self.type_id else ''
        neighborhood_name = self.neighborhood.name if self.neighborhood_id else ''

        if type_name and neighborhood_name:
            return f'{type_name} em {neighborhood_name}'

        return type_name or f'Imóvel {self.code}'

    def _next_code(self):
        # Trava a imobiliária para dois cadastros simultâneos não tirarem o mesmo código.
        Agency.objects.select_for_update().filter(pk=self.agency_id).first()
        # O código aceita letras, então a numeração automática olha só os puramente numéricos.
        numeric_codes = Property.objects.filter(
            agency_id=self.agency_id, code__regex=r'^[0-9]+$'
        ).values_list('code', flat=True)

        return str(max((int(code) for code in numeric_codes), default=0) + 1)

    def delete(self, deleted_by=None, *args, **kwargs):
        self.deleted_at = timezone.now()
        if deleted_by:
            self.deleted_by = deleted_by
        self.save()


def photo_upload_to(instance, filename):
    # Nome gerado aqui: o cliente não escolhe caminho nem sobrescreve arquivo de outra imobiliária.
    extension = Path(filename).suffix.lower()

    return (
        f'photos/{instance.parent.agency.slug}/'
        f'{instance.parent_field}-{uuid.uuid4().hex}{extension}'
    )


# A migration 0004 aponta para este nome, que existia antes da galeria virar genérica.
property_photo_upload_to = photo_upload_to


class Photo(models.Model):
    """Base das galerias de imóvel e de condomínio: mesma posição, miniatura e exclusão."""

    # Campo que aponta para o dono da galeria; também prefixa o arquivo salvo.
    parent_field = ''

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    image      = models.ImageField(upload_to=photo_upload_to)
    is_main    = models.BooleanField(default=False, help_text='Foto usada como miniatura')
    position   = models.PositiveSmallIntegerField(default=0, help_text='Ordem da foto na galeria')
    file_size  = models.PositiveIntegerField(default=0, help_text='Tamanho do arquivo em bytes')
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ('position', 'created_at')

    def __str__(self):
        return f'Foto de {self.parent}'

    @property
    def parent(self):
        return getattr(self, self.parent_field)

    def save(self, *args, **kwargs):
        if self._state.adding:
            # Foto nova entra no fim da galeria.
            if not self.position:
                last_position = self.parent.photos.aggregate(
                    last=models.Max('position')
                )['last']
                self.position = (last_position or 0) + 1

            # Lê o tamanho enquanto o arquivo ainda está em memória, sem ir ao storage depois.
            if self.image:
                self.file_size = self.image.size

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class PropertyPhoto(Photo):
    parent_field = 'property'

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='photos')

    class Meta(Photo.Meta):
        verbose_name = 'Foto do imóvel'
        verbose_name_plural = 'Fotos do imóvel'


class CondominiumPhoto(Photo):
    parent_field = 'condominium'

    condominium = models.ForeignKey(
        Condominium, on_delete=models.CASCADE, related_name='photos'
    )

    class Meta(Photo.Meta):
        verbose_name = 'Foto do condomínio'
        verbose_name_plural = 'Fotos do condomínio'


class PropertyPrice(models.Model):
    class Purpose(models.TextChoices):
        SALE = 'SALE', 'Comprar'
        RENT = 'RENT', 'Alugar'
        SEASONAL = 'SEASONAL', 'Temporada'

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property   = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='prices')
    purpose    = models.CharField(max_length=10, choices=Purpose.choices)
    amount     = models.DecimalField(max_digits=12, decimal_places=2)
    notes      = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Valor do imóvel'
        verbose_name_plural = 'Valores do imóvel'
        # Um imóvel pode ter venda e locação ao mesmo tempo, mas só um valor por finalidade.
        unique_together = ('property', 'purpose')

    def __str__(self):
        return f'{self.get_purpose_display()}: {self.amount}'


class PropertyFee(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property   = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='fees')
    fee        = models.ForeignKey(Fee, on_delete=models.PROTECT, related_name='property_fees')
    amount     = models.DecimalField(max_digits=10, decimal_places=2)
    notes      = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Taxa do imóvel'
        verbose_name_plural = 'Taxas do imóvel'
        unique_together = ('property', 'fee')

    def __str__(self):
        return f'{self.fee.name}: {self.amount}'


class PropertyExporter(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property   = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='exporters')
    exporter   = models.ForeignKey(Exporter, on_delete=models.PROTECT, related_name='properties')
    plan       = models.ForeignKey(ExporterPlan, on_delete=models.PROTECT, related_name='properties')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Exportador do imóvel'
        verbose_name_plural = 'Exportadores do imóvel'
        # Imóvel sem linha para o exportador é o mesmo que "Não exportar".
        unique_together = ('property', 'exporter')

    def __str__(self):
        return f'{self.exporter.name}: {self.plan.name}'


class PropertyHistory(models.Model):
    """Trilha do que mudou no imóvel: quem mexeu, quando e em quê.

    É registro de auditoria, então não tem edição nem exclusão lógica — a linha nasce e fica.
    O nome do autor é copiado no momento do registro para o histórico sobreviver à saída
    do usuário da imobiliária.
    """

    class Action(models.TextChoices):
        CREATED = 'CREATED', 'Cadastro do imóvel'
        UPDATED = 'UPDATED', 'Alteração do imóvel'
        PHOTOS_ADDED = 'PHOTOS_ADDED', 'Inclusão de imagens'
        PHOTOS_REMOVED = 'PHOTOS_REMOVED', 'Exclusão de imagens'
        PHOTOS_REORDERED = 'PHOTOS_REORDERED', 'Reordenação das imagens'

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property    = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='history')
    user        = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='property_changes')
    author_name = models.CharField(max_length=255, blank=True)
    action      = models.CharField(max_length=20, choices=Action.choices)
    notes       = models.CharField(max_length=255, blank=True)
    changes     = models.JSONField(default=list, blank=True, help_text='Lista de {label, from, to}')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Histórico do imóvel'
        verbose_name_plural = 'Histórico dos imóveis'
        ordering = ('-created_at',)
        indexes = [models.Index(fields=['property', '-created_at'])]

    def __str__(self):
        return f'{self.property_id} — {self.get_action_display()}'


class UserPermission(models.Model):
    """Nível de acesso de um usuário a um recurso do painel.

    Ausência de linha significa Sem acesso: a permissão falha fechada. O catálogo de
    recursos e a escada de níveis vivem em `core/resources.py`.
    """

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='permissions')
    resource   = models.CharField(max_length=40, choices=RESOURCE_CHOICES)
    level      = models.PositiveSmallIntegerField(
        choices=AccessLevel.choices, default=AccessLevel.NO_ACCESS
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Permissão do usuário'
        verbose_name_plural = 'Permissões do usuário'
        unique_together = ('user', 'resource')
        ordering = ('user', 'resource')

    def __str__(self):
        return f'{self.user.email} · {self.resource}: {self.get_level_display()}'


class Lead(models.Model):
    class Source(models.TextChoices):
        SITE = 'SITE', 'Site'
        PORTALS = 'PORTALS', 'Portais Imobiliários'
        WHATSAPP = 'WHATSAPP', 'WhatsApp'
        REFERRAL = 'REFERRAL', 'Indicação'
        SOCIAL_MEDIA = 'SOCIAL_MEDIA', 'Redes Sociais'
        PHONE = 'PHONE', 'Telefone'
        OTHER = 'OTHER', 'Outros'

    class Status(models.TextChoices):
        NEW = 'NEW', 'Novo'
        IN_CONTACT = 'IN_CONTACT', 'Em Contato'
        QUALIFIED = 'QUALIFIED', 'Qualificado'
        UNQUALIFIED = 'UNQUALIFIED', 'Não Qualificado'
        CONVERTED = 'CONVERTED', 'Convertido'

    class Interest(models.TextChoices):
        PURCHASE = 'PURCHASE', 'Compra'
        SALE = 'SALE', 'Venda'
        RENT = 'RENT', 'Locação'

    class QueueStatus(models.TextChoices):
        WAITING = 'WAITING', 'Na espera'
        OFFERED = 'OFFERED', 'Ofertado'
        ACCEPTED = 'ACCEPTED', 'Aceito'
        IN_SERVICE = 'IN_SERVICE', 'Em atendimento'
        CLOSED = 'CLOSED', 'Encerrado'

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency          = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='leads')
    code            = models.CharField(max_length=20, blank=True, help_text='Código do lead dentro da imobiliária')
    name            = models.CharField(max_length=150)
    email           = models.EmailField(max_length=255, blank=True)
    phone           = models.CharField(max_length=20, blank=True)
    source          = models.CharField(max_length=20, choices=Source.choices, default=Source.SITE)
    status          = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    interest        = models.CharField(max_length=20, choices=Interest.choices, default=Interest.PURCHASE)
    property_type   = models.CharField(max_length=60, blank=True, help_text='Tipo de imóvel de interesse')
    budget          = models.CharField(max_length=60, blank=True, help_text='Faixa de orçamento em texto livre')
    city            = models.CharField(max_length=100, blank=True)
    state           = models.CharField(max_length=2, blank=True)
    responsible     = models.ForeignKey(Broker, null=True, blank=True, on_delete=models.PROTECT, related_name='leads')
    observations    = models.TextField(blank=True)
    last_contact_at = models.DateField(null=True, blank=True)
    assigned_to     = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name='assigned_leads', help_text='Corretor (usuário) com o lead em mãos; a fila preenche ao aceitar')
    queue_status    = models.CharField(max_length=20, choices=QueueStatus.choices, blank=True, help_text='Vazio quando o lead não passou pela fila')
    queue_reason    = models.CharField(max_length=60, blank=True, help_text='Por que este corretor: rodízio, regra de retorno, menor carga, escolha do gestor')
    offered_at      = models.DateTimeField(null=True, blank=True)
    accepted_at     = models.DateTimeField(null=True, blank=True)
    contacted_at    = models.DateTimeField(null=True, blank=True, help_text='Primeiro contato registrado; para o relógio do SLA')
    queue_closed_at = models.DateTimeField(null=True, blank=True)
    deadline_at     = models.DateTimeField(null=True, blank=True, help_text='Fim do prazo da etapa atual: aceite ou primeira resposta')
    sla_breached    = models.BooleanField(default=False, help_text='Passou do prazo de primeira resposta; marcado uma vez')
    deleted_at      = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Lead'
        verbose_name_plural = 'Leads'
        ordering = ('-created_at',)
        unique_together = ('agency', 'code')

    def __str__(self):
        return f'{self.code} — {self.name}'

    def save(self, *args, **kwargs):
        if not self.code:
            with transaction.atomic():
                self.code = self._next_code()
                return super().save(*args, **kwargs)

        super().save(*args, **kwargs)

    def _next_code(self):
        # Trava a imobiliária para dois cadastros simultâneos não tirarem o mesmo código.
        Agency.objects.select_for_update().filter(pk=self.agency_id).first()
        numeric = Lead.objects.filter(
            agency_id=self.agency_id, code__regex=r'^LEAD[0-9]+$'
        ).values_list('code', flat=True)

        highest = max((int(code[4:]) for code in numeric), default=0)
        return f'LEAD{highest + 1:03d}'

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class LeadInteraction(models.Model):
    """Timeline do lead: anotações do corretor e cada transição na fila de atendimento. Não tem edição."""

    class Type(models.TextChoices):
        NOTE = 'NOTE', 'Ação registrada'
        ENQUEUED = 'ENQUEUED', 'Lead entrou na fila'
        OFFERED = 'OFFERED', 'Ofertado'
        ACCEPTED = 'ACCEPTED', 'Aceito'
        DECLINED = 'DECLINED', 'Recusado'
        EXPIRED = 'EXPIRED', 'Prazo de aceite estourado'
        FIRST_CONTACT = 'FIRST_CONTACT', 'Primeiro contato registrado'
        SLA_BREACH = 'SLA_BREACH', 'SLA de primeira resposta estourado'
        RETURNED = 'RETURNED', 'Devolvido à fila'
        ASSIGNED = 'ASSIGNED', 'Atribuído manualmente pelo gestor'
        HELD = 'HELD', 'Retido na espera'
        CLOSED = 'CLOSED', 'Atendimento encerrado'

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead        = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='interactions')
    type        = models.CharField(max_length=20, choices=Type.choices, default=Type.NOTE)
    user        = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name='lead_interactions', help_text='Corretor envolvido; vazio quando o evento é da própria fila')
    author_name = models.CharField(max_length=150, blank=True)
    text        = models.TextField()
    created_at  = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Interação do lead'
        verbose_name_plural = 'Interações do lead'
        ordering = ('created_at',)

    def __str__(self):
        return f'{self.lead.code}: {self.text[:40]}'


class ServiceTicket(models.Model):
    """Atendimento a cliente/interessado, com o vocabulário do ciclo imobiliário."""

    class Category(models.TextChoices):
        PURCHASE_INTEREST = 'PURCHASE_INTEREST', 'Interesse em compra'
        RENT_INTEREST = 'RENT_INTEREST', 'Interesse em locação'
        PROPERTY_VALUATION = 'PROPERTY_VALUATION', 'Avaliação de imóvel'
        VISIT_SCHEDULING = 'VISIT_SCHEDULING', 'Agendamento de visita'
        DOCUMENTATION = 'DOCUMENTATION', 'Documentação'
        POST_SALE = 'POST_SALE', 'Pós-venda'
        OTHER = 'OTHER', 'Outro'

    class Status(models.TextChoices):
        NEW = 'NEW', 'Novo'
        IN_PROGRESS = 'IN_PROGRESS', 'Em Andamento'
        AWAITING_RESPONSE = 'AWAITING_RESPONSE', 'Aguardando Retorno'
        RESOLVED = 'RESOLVED', 'Resolvido'
        CLOSED = 'CLOSED', 'Fechado'

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Baixa'
        NORMAL = 'NORMAL', 'Normal'
        HIGH = 'HIGH', 'Alta'
        URGENT = 'URGENT', 'Urgente'

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency        = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='service_tickets')
    protocol      = models.CharField(max_length=20, blank=True, help_text='Protocolo sequencial por ano, ex.: ATD-2026-001')
    client_name   = models.CharField(max_length=150)
    email         = models.EmailField(max_length=255, blank=True)
    phone         = models.CharField(max_length=20, blank=True)
    subject       = models.CharField(max_length=150)
    category      = models.CharField(max_length=30, choices=Category.choices, default=Category.OTHER)
    status        = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    priority      = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    responsible   = models.ForeignKey(Broker, null=True, blank=True, on_delete=models.PROTECT, related_name='service_tickets')
    property_code = models.CharField(max_length=20, blank=True, help_text='Código do imóvel relacionado')
    description   = models.TextField(blank=True)
    deleted_at    = models.DateTimeField(null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Atendimento'
        verbose_name_plural = 'Atendimentos'
        ordering = ('-created_at',)
        unique_together = ('agency', 'protocol')

    def __str__(self):
        return f'{self.protocol} — {self.subject}'

    def save(self, *args, **kwargs):
        if not self.protocol:
            with transaction.atomic():
                self.protocol = self._next_protocol()
                return super().save(*args, **kwargs)

        super().save(*args, **kwargs)

    def _next_protocol(self):
        Agency.objects.select_for_update().filter(pk=self.agency_id).first()
        year = timezone.localdate().year
        prefix = f'ATD-{year}-'
        existing = ServiceTicket.objects.filter(
            agency_id=self.agency_id, protocol__startswith=prefix
        ).values_list('protocol', flat=True)

        highest = max(
            (int(protocol[len(prefix):]) for protocol in existing if protocol[len(prefix):].isdigit()),
            default=0,
        )
        return f'{prefix}{highest + 1:03d}'

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class ServiceTicketMessage(models.Model):
    class AuthorType(models.TextChoices):
        AGENT = 'AGENT', 'Atendente'
        CLIENT = 'CLIENT', 'Cliente'

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket      = models.ForeignKey(ServiceTicket, on_delete=models.CASCADE, related_name='messages')
    author_name = models.CharField(max_length=150, blank=True)
    author_type = models.CharField(max_length=10, choices=AuthorType.choices, default=AuthorType.AGENT)
    message     = models.TextField()
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Mensagem do atendimento'
        verbose_name_plural = 'Mensagens do atendimento'
        ordering = ('created_at',)

    def __str__(self):
        return f'{self.ticket.protocol}: {self.message[:40]}'


class Task(models.Model):
    class Type(models.TextChoices):
        CALL = 'CALL', 'Ligação'
        EMAIL = 'EMAIL', 'E-mail'
        VISIT = 'VISIT', 'Visita'
        MEETING = 'MEETING', 'Reunião'
        FOLLOW_UP = 'FOLLOW_UP', 'Follow-up'
        DOCUMENTATION = 'DOCUMENTATION', 'Documentação'
        NEGOTIATION = 'NEGOTIATION', 'Negociação'
        OTHER = 'OTHER', 'Outro'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendente'
        IN_PROGRESS = 'IN_PROGRESS', 'Em Andamento'
        DONE = 'DONE', 'Concluída'

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Baixa'
        NORMAL = 'NORMAL', 'Normal'
        HIGH = 'HIGH', 'Alta'
        URGENT = 'URGENT', 'Urgente'

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency        = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='tasks')
    title         = models.CharField(max_length=150)
    description   = models.TextField(blank=True)
    type          = models.CharField(max_length=20, choices=Type.choices, default=Type.OTHER)
    status        = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    priority      = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    responsible   = models.ForeignKey(Broker, null=True, blank=True, on_delete=models.PROTECT, related_name='tasks')
    due_date      = models.DateField()
    due_time      = models.TimeField(null=True, blank=True)
    lead          = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks')
    deal          = models.ForeignKey('Deal', null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks')
    property_code = models.CharField(max_length=20, blank=True, help_text='Código do imóvel, obrigatório em visitas')
    notes         = models.TextField(blank=True)
    deleted_at    = models.DateTimeField(null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tarefa'
        verbose_name_plural = 'Tarefas'
        ordering = ('due_date', 'due_time')

    def __str__(self):
        return self.title

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class Deal(models.Model):
    """Negócio do funil de vendas. `outcome` vazio = ativo no quadro; preenchido = encerrado."""

    class Stage(models.TextChoices):
        QUALIFICATION = 'QUALIFICATION', 'Qualificação'
        VISIT_SCHEDULED = 'VISIT_SCHEDULED', 'Visita agendada'
        VISIT_DONE = 'VISIT_DONE', 'Visita realizada'
        PROPOSAL = 'PROPOSAL', 'Proposta'
        NEGOTIATION = 'NEGOTIATION', 'Negociação'
        CLOSING = 'CLOSING', 'Fechamento'

    class Type(models.TextChoices):
        SALE = 'SALE', 'Venda'
        RENT = 'RENT', 'Locação'
        SEASONAL = 'SEASONAL', 'Temporada'

    class Outcome(models.TextChoices):
        WON = 'WON', 'Ganho'
        LOST = 'LOST', 'Perdido'

    class LossReason(models.TextChoices):
        PRICE = 'PRICE', 'Preço'
        FINANCING_DENIED = 'FINANCING_DENIED', 'Financiamento negado'
        BOUGHT_OTHER = 'BOUGHT_OTHER', 'Comprou/alugou outro imóvel'
        GAVE_UP = 'GAVE_UP', 'Desistiu da busca'
        NO_RESPONSE = 'NO_RESPONSE', 'Sem retorno'
        OTHER = 'OTHER', 'Outro'

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency          = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='deals')
    title           = models.CharField(max_length=150)
    client_name     = models.CharField(max_length=150)
    value           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stage           = models.CharField(max_length=20, choices=Stage.choices, default=Stage.QUALIFICATION)
    probability     = models.PositiveSmallIntegerField(default=10)
    estimated_close = models.DateField(null=True, blank=True)
    responsible     = models.ForeignKey(Broker, null=True, blank=True, on_delete=models.PROTECT, related_name='deals')
    origin          = models.CharField(max_length=20, choices=Lead.Source.choices, blank=True)
    type            = models.CharField(max_length=10, choices=Type.choices, blank=True)
    property_code   = models.CharField(max_length=20, blank=True)
    description     = models.TextField(blank=True)
    notes           = models.TextField(blank=True)
    outcome         = models.CharField(max_length=10, choices=Outcome.choices, null=True, blank=True)
    loss_reason     = models.CharField(max_length=20, choices=LossReason.choices, blank=True)
    closed_at       = models.DateField(null=True, blank=True)
    lead            = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.SET_NULL, related_name='deals')
    deleted_at      = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Negócio'
        verbose_name_plural = 'Negócios'
        ordering = ('-created_at',)

    def __str__(self):
        return self.title

    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


def default_business_days():
    # Segunda a sábado, na convenção 0 = domingo que o painel usa.
    return [1, 2, 3, 4, 5, 6]


class AgencySettings(models.Model):
    """Configurações do painel: um único registro por imobiliária, criado no primeiro acesso."""

    class QueueMode(models.TextChoices):
        SEQUENTIAL = 'SEQUENTIAL', 'Rodízio sequencial'
        LOAD = 'LOAD', 'Menor carga'
        RANDOM = 'RANDOM', 'Aleatório'
        MANUAL = 'MANUAL', 'Manual (gestor distribui)'

    class QueueDeclineBehavior(models.TextChoices):
        END = 'END', 'Vai para o final da fila'
        KEEP = 'KEEP', 'Mantém a posição na fila'

    class QueueOffHours(models.TextChoices):
        HOLD = 'HOLD', 'Fica na espera até abrir'
        DISTRIBUTE = 'DISTRIBUTE', 'Distribui mesmo assim'

    id                   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency               = models.OneToOneField(Agency, on_delete=models.CASCADE, related_name='settings')
    system_name          = models.CharField(max_length=100, blank=True)
    site_url             = models.URLField(max_length=200, blank=True)
    site_description     = models.TextField(blank=True)
    contact_email        = models.EmailField(max_length=255, blank=True)
    phone                = models.CharField(max_length=20, blank=True)
    whatsapp             = models.CharField(max_length=20, blank=True)
    address              = models.CharField(max_length=255, blank=True)
    sender_email         = models.EmailField(max_length=255, blank=True)
    sender_name          = models.CharField(max_length=100, blank=True)
    cc_email             = models.EmailField(max_length=255, blank=True, help_text='Recebe cópia de todos os e-mails')
    primary_color        = models.CharField(max_length=7, default='#003533')
    secondary_color      = models.CharField(max_length=7, default='#0ba7a0')
    logo_url             = models.URLField(max_length=200, blank=True)
    favicon_url          = models.URLField(max_length=200, blank=True)
    google_analytics_id  = models.CharField(max_length=50, blank=True)
    google_maps_key      = models.CharField(max_length=100, blank=True)
    recaptcha_site_key   = models.CharField(max_length=100, blank=True)
    recaptcha_secret_key = models.CharField(max_length=100, blank=True)
    facebook_url         = models.URLField(max_length=200, blank=True)
    instagram_url        = models.URLField(max_length=200, blank=True)
    property_code_auto_increment = models.BooleanField(default=True)
    property_code_prefix = models.CharField(max_length=10, blank=True, default='IMV')
    queue_mode                   = models.CharField(max_length=20, choices=QueueMode.choices, default=QueueMode.SEQUENTIAL)
    queue_auto_assign            = models.BooleanField(default=True, help_text='Entrega o lead já aceito a quem está na vez, sem etapa de aceite')
    queue_decline_behavior       = models.CharField(max_length=10, choices=QueueDeclineBehavior.choices, default=QueueDeclineBehavior.END)
    queue_accept_minutes         = models.PositiveSmallIntegerField(default=3, help_text='Minutos para aceitar a oferta; estourado, o lead passa ao próximo')
    queue_first_response_minutes = models.PositiveSmallIntegerField(default=5, help_text='Minutos, a partir do aceite, para registrar o primeiro contato')
    queue_max_active_per_broker  = models.PositiveSmallIntegerField(default=3, help_text='Atendimentos simultâneos por corretor; 0 = sem teto')
    queue_return_window_days     = models.PositiveSmallIntegerField(default=30, help_text='Cliente que volta nesta janela cai com o mesmo corretor; 0 = desligado')
    queue_skips_before_pause     = models.PositiveSmallIntegerField(default=2, help_text='Ofertas perdidas seguidas até pausar o corretor sozinho; 0 = nunca')
    queue_business_start         = models.TimeField(default=datetime.time(8, 0))
    queue_business_end           = models.TimeField(default=datetime.time(23, 30))
    queue_business_days          = models.JSONField(default=default_business_days, blank=True, help_text='Dias do expediente, 0 = domingo … 6 = sábado')
    queue_off_hours              = models.CharField(max_length=20, choices=QueueOffHours.choices, default=QueueOffHours.HOLD)
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configurações da imobiliária'
        verbose_name_plural = 'Configurações das imobiliárias'

    def __str__(self):
        return f'Configurações de {self.agency.name}'


class AssistantConversation(models.Model):
    """Conversa de um usuário com o assistente Theo; cada usuário só enxerga as próprias."""

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency     = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='assistant_conversations')
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assistant_conversations')
    title      = models.CharField(max_length=120, blank=True, help_text='Primeira pergunta da conversa')
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Conversa do assistente'
        verbose_name_plural = 'Conversas do assistente'
        ordering = ('-updated_at',)

    def __str__(self):
        return self.title or f'Conversa {self.pk}'

    def delete(self, deleted_by=None, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save()


class AssistantMessage(models.Model):
    """Mensagem da conversa com o Theo. É registro de histórico: não tem edição nem exclusão."""

    class Role(models.TextChoices):
        USER = 'USER', 'Usuário'
        ASSISTANT = 'ASSISTANT', 'Assistente'

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(AssistantConversation, on_delete=models.CASCADE, related_name='messages')
    role         = models.CharField(max_length=10, choices=Role.choices)
    content      = models.TextField()
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Mensagem do assistente'
        verbose_name_plural = 'Mensagens do assistente'
        ordering = ('created_at',)

    def __str__(self):
        return f'{self.get_role_display()}: {self.content[:40]}'
