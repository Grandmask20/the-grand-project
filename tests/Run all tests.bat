@echo off
rem Runs the regression tests one after another (several minutes; the viewer test opens a window).
cd /d "%~dp0.."
for %%t in (test_atlas_builder test_atlas_io test_model_safety test_atlas_folder test_random_sequence test_drop_placement test_false_merge test_detect_pairs test_atlas_viewer) do (
  echo ===== %%t
  py -m tests.%%t
)
pause
