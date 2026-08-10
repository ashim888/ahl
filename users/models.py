from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserManager(BaseUserManager):
    """Manager for the email-based custom User model."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', User.Role.ADMIN)
        extra_fields.setdefault('is_verified', True)
        extra_fields.setdefault('verification_status', User.VerificationStatus.APPROVED)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user, authenticated by email instead of username."""

    class Role(models.TextChoices):
        UNVERIFIED = 'unverified', 'Unverified'
        VERIFIED_AUTHOR = 'verified_author', 'Verified Author'
        REVIEWER = 'reviewer', 'Reviewer'
        EDITOR = 'editor', 'Editor'
        EDITOR_IN_CHIEF = 'editor_in_chief', 'Editor-in-Chief'
        ADMIN = 'admin', 'Admin'

    class VerificationStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    username = None
    email = models.EmailField('email address', unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)

    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.UNVERIFIED,
        help_text='Determines what the user is permitted to do across the journal.',
    )
    is_verified = models.BooleanField(default=False)
    verification_status = models.CharField(
        max_length=20, choices=VerificationStatus.choices, default=VerificationStatus.PENDING,
    )

    orcid = models.CharField(
        max_length=19, unique=True, null=True, blank=True,
        help_text='ORCID iD, e.g. 0000-0002-1825-0097.',
    )
    affiliation = models.CharField(max_length=255, null=True, blank=True)
    department = models.CharField(max_length=255, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    cv_file = models.FileField(upload_to='profiles/cvs/', null=True, blank=True)
    research_interests = models.TextField(null=True, blank=True)
    linkedin_url = models.URLField(null=True, blank=True)
    researchgate_url = models.URLField(null=True, blank=True)
    publications = models.TextField(
        null=True, blank=True,
        help_text='Prior publication history, reviewed by an editor during verification.',
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = UserManager()

    def __str__(self):
        return f'{self.get_full_name()} <{self.email}>'
