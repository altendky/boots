import sys

import attr
import yaml


@attr.s
class Platform:
    name = attr.ib()
    vm_image = attr.ib()


@attr.s
class PythonVersion:
    version = attr.ib()
    architecture = attr.ib()

    def version_string(self):
        return '.'.join(str(x) for x in self.version)

    def to_string(self):
        return '{}-{}'.format(self.version_string(), self.architecture)


@attr.s
class MatrixJob:
    platform = attr.ib()
    python_version = attr.ib()

    def job_name(self):
        return '{}_Python_{}'.format(
            self.platform.name,
            self.python_version.to_string(),
        ).lower().replace('.', '_').replace('-', '_')

    def display_name(self):
        return '{}: Python {}'.format(
            self.platform.name,
            self.python_version.to_string(),
        )

    def environment_string(self):
        return '{}_{}'.format(
            self.platform.name,
            self.python_version.to_string(),
        )

    def to_list(self):
        return [
            self.job_name(),
            {
                'platform': self.platform.name,
                'vmImage': self.platform.vm_image,
                'versionSpec': self.python_version.version_string(),
                'architecture': self.python_version.architecture,
                'displayName': self.display_name(),
                'job': self.job_name(),
                'environment': self.environment_string(),
            },
        ]


def main():
    platforms = [
        Platform(name='Linux', vm_image='ubuntu-16.04'),
        Platform(name='macOS', vm_image='macOS-10.13'),
        Platform(name='Windows', vm_image='vs2017-win2016'),
    ]

    python_versions = [
        PythonVersion(version=version, architecture=architecture)
        for version in [(3, 6), (3, 7)]
        for architecture in ['x64']
    ]

    matrix_jobs = [
        MatrixJob(platform=platform, python_version=python_version)
        for platform in platforms
        for python_version in python_versions
    ]

    strategy = {
        'strategy': {
            'matrix': dict(job.to_list() for job in matrix_jobs),
        },
    }

    jobs = {
        'jobs': [
            {
                'job': '${{ parameters.job }}',
                'displayName': '${{ parameters.displayName }}',
                'dependsOn': 'BOOTS_ENVIRONMENTS',
                'pool': {
                    'vmImage': '${{ parameters.vmImage }}',
                },
                'condition': "contains(dependencies.BOOTS_ENVIRONMENTS.outputs['v.v'], '|${{ parameters.environment }}')",
                **strategy,
                'steps': [
                    {
                        'task': 'UsePythonVersion@0',
                        'inputs': {
                            'versionSpec': '${{ parameters.versionSpec }}',
                            'architecture': '${{ parameters.architecture }}',
                        },
                    },
                    {
                        'template': '../steps/in_archive_from_artifact.yml',
                    },
                    {
                        'bash': '${{ parameters.command }}',
                        'displayName': 'Run Command',
                    },
                    {
                        'task': 'CopyFiles@2',
                        'inputs': {
                            'contents': 'requirements/*.txt',
                            'targetFolder': '$(Build.ArtifactStagingDirectory)',
                        },
                    },
                    {
                        'task': 'PublishBuildArtifacts@1',
                        'inputs': {
                            'pathToPublish': '$(Build.ArtifactStagingDirectory)',
                            'artifactName': 'results',
                        },
                    },
                ],
            },
        ],
    }

    yaml.safe_dump(strategy, stream=sys.stdout)


if __name__ == '__main__':
    sys.exit(main())
