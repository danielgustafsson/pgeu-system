from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.conf import settings

import subprocess
import os.path


def _validate_monitor_request(request):
    if request.META['REMOTE_ADDR'] not in settings.MONITOR_SERVER_IPS:
        raise PermissionDenied("Invalid IP")


def gitinfo(request):
    _validate_monitor_request(request)

    # Get information about our current position in the git structure
    def _run_git(*args):
        p = subprocess.run(
            ['git', ] + list(args),
            stdout=subprocess.PIPE,
            cwd=os.path.abspath(os.path.dirname(__file__)),
            timeout=2,
            check=True,
            universal_newlines=True,
        )
        if p.stdout:
            return p.stdout.splitlines()[0]
        return ""

    branch = _run_git('symbolic-ref', '--short', 'HEAD')
    tag = _run_git('tag', '--points-at', 'HEAD')
    commitandtime = _run_git('log', '-1', '--format=%H;%cI')

    return HttpResponse("{};{};{}".format(branch, tag, commitandtime), content_type='text/plain')
