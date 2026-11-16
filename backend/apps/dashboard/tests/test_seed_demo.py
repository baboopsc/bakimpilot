"""The deploy hook runs `seed_demo --if-empty` on every boot, so it must be safe to repeat."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.ai.models import ManualDocument
from apps.fleet.models import Aircraft

pytestmark = pytest.mark.django_db


def test_seed_once_then_if_empty_is_a_no_op_that_restores_the_pdf():
    call_command("seed_demo")
    aircraft, users = Aircraft.objects.count(), User.objects.count()
    assert aircraft == 6 and User.objects.filter(username="planner").exists()

    doc = ManualDocument.objects.get()
    assert doc.chunks.exists()
    doc.file.storage.delete(doc.file.name)  # what a restart on an ephemeral disk does

    call_command("seed_demo", "--if-empty")
    assert (Aircraft.objects.count(), User.objects.count()) == (aircraft, users)  # nothing duplicated
    doc.refresh_from_db()
    assert doc.file.storage.exists(doc.file.name)

    with pytest.raises(CommandError):
        call_command("seed_demo")  # without the flag it still refuses to double-seed
