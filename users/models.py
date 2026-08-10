import datetime

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from .validators import cv_extension_validator, validate_cv_file_size


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

    REAPPLY_COOLDOWN_DAYS = 30

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
    verification_status_changed_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Stamped automatically whenever verification_status changes (see signals.py). '
                   'Used to enforce the 30-day reapply cooldown after rejection.',
    )

    orcid = models.CharField(
        max_length=19, unique=True, null=True, blank=True,
        help_text='ORCID iD, e.g. 0000-0002-1825-0097.',
    )
    affiliation = models.CharField(max_length=255, null=True, blank=True)
    department = models.CharField(max_length=255, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    cv_file = models.FileField(
        upload_to='profiles/cvs/', null=True, blank=True,
        validators=[cv_extension_validator, validate_cv_file_size],
        help_text='PDF, DOC, or DOCX, up to 10 MB.',
    )
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

    @property
    def reapply_available_at(self):
        """When a rejected user becomes eligible to reapply, or None if not applicable."""
        if self.verification_status != self.VerificationStatus.REJECTED or not self.verification_status_changed_at:
            return None
        return self.verification_status_changed_at + datetime.timedelta(days=self.REAPPLY_COOLDOWN_DAYS)

    @property
    def can_reapply(self):
        available_at = self.reapply_available_at
        return available_at is not None and timezone.now() >= available_at

    # Roles governed by the self-registration verification queue. Reviewer/Editor/
    # Editor-in-Chief/Admin are assigned manually (see ARCHITECTURE.md §6.1) and are
    # deliberately out of scope for approve_verification/reject_verification below,
    # so a bulk queue action can never downgrade an already-privileged account.
    VERIFICATION_QUEUE_ROLES = (Role.UNVERIFIED, Role.VERIFIED_AUTHOR)

    def approve_verification(self):
        """Promote to Verified Author. No-op (returns False) for roles the
        verification queue doesn't govern, e.g. Editor/EiC/Admin.
        """
        if self.role not in self.VERIFICATION_QUEUE_ROLES:
            return False
        self.verification_status = self.VerificationStatus.APPROVED
        self.is_verified = True
        self.role = self.Role.VERIFIED_AUTHOR
        self.save()
        return True

    def reject_verification(self):
        """Reject (or revoke) author verification, reverting role to unverified.
        No-op (returns False) for roles the verification queue doesn't govern.
        """
        if self.role not in self.VERIFICATION_QUEUE_ROLES:
            return False
        self.verification_status = self.VerificationStatus.REJECTED
        self.is_verified = False
        self.role = self.Role.UNVERIFIED
        self.save()
        return True
