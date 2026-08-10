from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render

from users.decorators import verification_required

from .forms import RevisionUploadForm, SubmissionFormStep1, SubmissionFormStep2, SubmissionFormStep3
from .models import ManuscriptFile, Submission
from .validators import infer_manuscript_file_type

WIZARD_SESSION_KEY = 'submission_wizard'


def _wizard_data(request):
    return request.session.get(WIZARD_SESSION_KEY, {})


@verification_required
def submit_step1(request):
    wizard_data = _wizard_data(request)

    if request.method == 'POST':
        form = SubmissionFormStep1(request.POST)
        if form.is_valid():
            wizard_data['step1'] = form.cleaned_data
            request.session[WIZARD_SESSION_KEY] = wizard_data
            return redirect('submissions:submit_step2')
    else:
        form = SubmissionFormStep1(initial=wizard_data.get('step1'))

    return render(request, 'submissions/submit_step1.html', {'form': form, 'step': 1})


@verification_required
def submit_step2(request):
    wizard_data = _wizard_data(request)
    if 'step1' not in wizard_data:
        messages.error(request, 'Start with the manuscript details first.')
        return redirect('submissions:submit_step1')

    if request.method == 'POST':
        form = SubmissionFormStep2(request.POST, request.FILES)
        if form.is_valid():
            if not request.session.session_key:
                request.session.save()
            uploaded = form.cleaned_data['file']
            temp_path = default_storage.save(
                f'manuscripts/_wizard_tmp/{request.session.session_key}/{uploaded.name}', uploaded,
            )
            wizard_data['step2'] = {
                'temp_path': temp_path,
                'original_name': uploaded.name,
                'file_type': infer_manuscript_file_type(uploaded.name),
            }
            request.session[WIZARD_SESSION_KEY] = wizard_data
            return redirect('submissions:submit_step3')
    else:
        form = SubmissionFormStep2()

    return render(request, 'submissions/submit_step2.html', {'form': form, 'step': 2})


@verification_required
def submit_step3(request):
    wizard_data = _wizard_data(request)
    if 'step1' not in wizard_data:
        return redirect('submissions:submit_step1')
    if 'step2' not in wizard_data:
        return redirect('submissions:submit_step2')

    if request.method == 'POST':
        form = SubmissionFormStep3(request.POST)
        if form.is_valid():
            step1, step2 = wizard_data['step1'], wizard_data['step2']

            submission = Submission.objects.create(submitter=request.user, **step1)

            with default_storage.open(step2['temp_path']) as temp_file:
                content = ContentFile(temp_file.read())
            manuscript = ManuscriptFile(
                submission=submission, file_type=step2['file_type'], version=1,
            )
            manuscript.file.save(step2['original_name'], content, save=True)
            default_storage.delete(step2['temp_path'])

            del request.session[WIZARD_SESSION_KEY]
            messages.success(request, 'Manuscript submitted. You can track its status on your dashboard.')
            return redirect('submissions:author_dashboard')
    else:
        form = SubmissionFormStep3()

    return render(request, 'submissions/submit_step3.html', {
        'form': form, 'step': 3,
        'step1': wizard_data['step1'], 'step2': wizard_data['step2'],
    })


@verification_required
def author_dashboard(request):
    submissions = Submission.objects.filter(submitter=request.user).select_related(
        'editor_assigned',
    ).prefetch_related('manuscript_files').order_by('-submission_date')
    revision_form = RevisionUploadForm()
    return render(request, 'submissions/author_dashboard.html', {
        'submissions': submissions, 'revision_form': revision_form,
    })


@verification_required
def upload_revision(request, pk):
    submission = get_object_or_404(Submission, pk=pk, submitter=request.user)

    if request.method != 'POST':
        return redirect('submissions:author_dashboard')

    if submission.status not in (Submission.Status.MINOR_REVISION, Submission.Status.MAJOR_REVISION):
        messages.error(request, 'This submission is not currently awaiting a revision upload.')
        return redirect('submissions:author_dashboard')

    form = RevisionUploadForm(request.POST, request.FILES)
    if form.is_valid():
        uploaded = form.cleaned_data['file']
        next_version = (submission.manuscript_files.aggregate(Max('version'))['version__max'] or 0) + 1
        manuscript = ManuscriptFile(
            submission=submission, file_type=infer_manuscript_file_type(uploaded.name), version=next_version,
        )
        manuscript.file.save(uploaded.name, uploaded, save=True)

        submission.revision_round += 1
        submission.status = Submission.Status.UNDER_REVIEW
        submission.save()
        messages.success(request, 'Revision uploaded — your submission is back under editorial review.')
    else:
        messages.error(request, 'Revision upload failed: ' + ' '.join(
            f'{field}: {", ".join(errs)}' for field, errs in form.errors.items()
        ))

    return redirect('submissions:author_dashboard')
