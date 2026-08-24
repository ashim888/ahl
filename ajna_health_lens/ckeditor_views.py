from django_ckeditor_5.views import upload_file

from users.decorators import role_required
from users.models import User

# Wraps the package's own upload view with this project's RBAC instead of
# relying on CKEDITOR_5_FILE_UPLOAD_PERMISSION (see the setting's comment in
# settings.py for why neither of its two built-in modes fits here). This is
# registered under the exact view name (ck_editor_5_upload_file) the widget
# already reverses, in place of the package's own urls.py.
ckeditor5_upload_file = role_required(*User.EDITORIAL_ROLES)(upload_file)
