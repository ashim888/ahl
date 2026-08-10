TAILWIND_INPUT = 'w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900'


def apply_tailwind_widgets(form, skip=('cv_file', 'file')):
    """Add TAILWIND_INPUT styling to every field's widget except file inputs,
    which are styled by the browser and don't take the same classes usefully.
    """
    for name, field in form.fields.items():
        if name in skip:
            continue
        field.widget.attrs['class'] = TAILWIND_INPUT
    return form
