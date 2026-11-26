"""tools.make_release: every release's notes say how to install and start it (manny), from the README."""

from grand_project.app import constants as K
from grand_project.app import updater
from tools import make_release


def test_the_release_has_no_atlases_folder_to_replace_the_players():
    import inspect

    # (shipped for its .gitkeep, copying an update over with macOS Finder's Replace swapped the player's atlases)
    assert "atlases/*" in make_release.GITIGNORE and "!atlases" not in make_release.GITIGNORE
    assert '"atlases"' not in inspect.getsource(make_release.main)
    assert not any(f.startswith("atlases/") for f in make_release.FILES + make_release.TREES)


def test_the_release_notes_say_which_files_to_run_on_each_system():
    notes = make_release.release_notes("1.3.1")
    assert f"Program version v{make_release.version()}." in notes
    assert "| **Windows** |" in notes and "| **macOS / Linux** |" in notes  # the table of files to run
    assert "Install (run once).bat" in notes and "./install.sh" in notes and "./start.sh" in notes
    assert "### Get it" not in notes  # (the download page is where the notes are read)
    # what's new first, under the release's header, then the divider the in-app update stops at (user's layout)
    cut = f"\n\n{K.UPDATE_NOTES_CUT}\n\n"
    assert notes.startswith("## 1.3.1\n\n- ") and notes.index(cut) < notes.index("## How to install")
    assert updater.whats_new(notes) == "## 1.3.1\n\n- (write the highlights here)"  # (the update box: no install)
    readme = (make_release.HERE / "README.md").read_text(encoding="utf-8")
    assert "#### First time" in notes and "### First time" in readme  # the same section, a level down
