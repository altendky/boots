import glob
import json

import requests
import requests.auth


# TODO: CAMPid 0743105874017581374310081
def make_remote_lock_archive():
    import tarfile
    import io

    archive_file = io.BytesIO()

    archive = tarfile.TarFile(mode='w', fileobj=archive_file)

    patterns = (
        'boots.py',
        'setup.cfg',
        'requirements/*.in',
    )

    for pattern in patterns:
        for path in glob.glob(pattern):
            archive.add(path)

    archive.close()

    return archive_file.getvalue()


def post_file(data):
    response = requests.post(
        url='https://file.io/',
        params={'expires': '1w'},
        files={'file': ('archive.tar.gz', data)},
    )

    response.raise_for_status()
    response_json = response.json()

    if not response_json['success']:
        raise Exception('failed to upload archive')

    return response_json['link']


def request_remote_lock_build(archive_url, username, personal_access_token):
    parameters = {'BOOTS_ARCHIVE_URL': archive_url}

    response = requests.post(
        url=(
            'https://dev.azure.com'
            '/altendky/boots/_apis/build/builds?api-version=5.0'
        ),
        auth=requests.auth.HTTPBasicAuth(
            username,
            personal_access_token,
        ),
        json={
            "definition": {"id": 2},
            "sourceBranch": "lock_in_azure",
            "parameters": json.dumps(parameters),
        },
    )

    response.raise_for_status()
    response_json = response.json()

    build_url = (
        'https://dev.azure.com/altendky/boots/_build/results?buildId={}'
    )

    return build_url.format(response_json['id'])
