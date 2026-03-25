%global srcname mockpod

%if 0%{?git_build}
%global pkg_name %{srcname}-git
%else
%global pkg_name %{srcname}
%endif


Name:           %{pkg_name}
Version:        0.1.0
Release:        %autorelease
Summary:        Run mock RPM builds in Podman with local repo management

License:        GPL-3.0-or-later
URL:            https://github.com/nikromen/mockpod
Source:         %{srcname}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-pytest

Requires:       podman
Requires:       crun-krun

%if 0%{?git_build}
Conflicts:      mockpod
%else
Conflicts:      mockpod-git
%endif


%description
mockpod builds RPM packages inside isolated Podman containers using mock.
It manages a local artifact repository with dependency resolution, build
caching, and versioned history. Built RPMs can be served as a DNF repo
over HTTP.
%if 0%{?git_build}

This is a development build from the main branch.
%endif


%prep
%autosetup -n %{srcname}-%{version}


%generate_buildrequires
%pyproject_buildrequires


%build
%pyproject_wheel


%install
%pyproject_install
%pyproject_save_files %{srcname}


%check
%pytest -vvv --log-level DEBUG tests/unit


%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/%{srcname}


%changelog
%autochangelog
