# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright (c) 2021 ScyllaDB

from textwrap import dedent


# pylint: disable=anomalous-backslash-in-string


def configure_rsyslog_rate_limits_script(interval: int, burst: int) -> str:
    # Configure rsyslog.  Use obsolete legacy format here because it's easier to redefine imjournal parameters.
    return dedent(fr"""
    grep imjournalRatelimitInterval /etc/rsyslog.conf | cat <<EOF >> /etc/rsyslog.conf
    #
    # The following configuration was added by SCT.
    #
    \$ModLoad imjournal
    \$imjournalRatelimitInterval {interval}
    \$imjournalRatelimitBurst {burst}
    EOF
    """)


def configure_rsyslog_target_script(host: str, port: int) -> str:
    return f'echo "action(type=\\"omfwd\\" Target=\\"{host}\\" Port=\\"{port}\\" Protocol=\\"tcp\\")" >> /etc/rsyslog.conf\n'


def configure_rsyslog_set_hostname_script(host: str) -> str:
    return dedent(f"""
    if ! grep "\\$LocalHostname {host}" /etc/rsyslog.conf; then
        echo "" >> /etc/rsyslog.conf
        echo "\\$LocalHostname {host}" >> /etc/rsyslog.conf
    fi
    """)


def configure_hosts_set_hostname_script(host: str) -> str:
    return f'grep -P "127.0.0.1[^\\\\n]+{host}" /etc/hosts || sed -ri "s/(127.0.0.1[ \\t]+' \
           f'localhost[^\\n]*)$/\\1\\t{host}/" /etc/hosts\n'


def configure_sshd_script():
    return dedent("""
    sed -i -e 's/^\*[[:blank:]]*soft[[:blank:]]*nproc[[:blank:]]*4096/*\t\tsoft\tnproc\t\tunlimited/' \
        /etc/security/limits.d/20-nproc.conf
    echo -e '*\t\thard\tnproc\t\tunlimited' >> /etc/security/limits.d/20-nproc.conf

    sed -i 's/#MaxSessions \(.*\)$/MaxSessions 1000/' /etc/ssh/sshd_config
    sed -i 's/#MaxStartups \(.*\)$/MaxStartups 60/' /etc/ssh/sshd_config
    sed -i 's/#LoginGraceTime \(.*\)$/LoginGraceTime 15s/' /etc/ssh/sshd_config
    """)


def restart_sshd_service():
    return "systemctl restart sshd\n"


def restart_rsyslog_service():
    return "systemctl restart rsyslog\n"
