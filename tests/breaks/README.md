# Breaks files for `make break-check`

Each file lists behaviours to break one at a time, to prove some test notices each one
(`tools/break_check.py` says how).

- `architecture-review.json`: the 19 fixes from the Architecture viewer review of 2026-10-02.
  On 2026-10-02 all 19 were noticed.

Against every viewer test (about 100 s per break):

    make break-check BREAKS=tests/breaks/architecture-review.json

Faster, against only the 16 tests written for these fixes (about 4 minutes):

    python3 tools/break_check.py --breaks tests/breaks/architecture-review.json --tests \
      tests/test_architecture_view.py::test_a_line_inside_a_shared_sub_use_case_carries_the_step_that_runs_it \
      tests/test_viewer_browser.py::test_a_line_cards_feature_rows_carry_no_glossary_link \
      tests/test_viewer_browser.py::test_a_line_names_its_use_cases_by_feature \
      tests/test_viewer_browser.py::test_a_line_up_the_layers_points_the_way_it_runs_and_is_picked_the_way_it_runs \
      tests/test_viewer_browser.py::test_a_picked_arrows_head_turns_with_it_and_comes_back \
      tests/test_viewer_browser.py::test_a_picture_drawn_again_under_a_resting_pointer_previews_nothing \
      tests/test_viewer_browser.py::test_a_use_case_maps_step_badges_are_whole_on_their_arrows \
      tests/test_viewer_browser.py::test_a_use_case_whose_step_has_no_words_is_still_on_the_lines_card \
      tests/test_viewer_browser.py::test_an_interfaces_card_drops_only_the_people_this_picture_joins_to_it \
      tests/test_viewer_browser.py::test_picking_what_the_second_card_shows_keeps_its_contents_in_place_near_the_drawings_top \
      tests/test_viewer_browser.py::test_the_happy_path_switch_is_only_on_a_feature_with_a_happy_path_picture \
      tests/test_viewer_browser.py::test_the_second_card_leaves_the_file_tree_to_what_is_picked \
      tests/test_viewer_browser.py::test_the_second_card_never_lands_on_the_main_card_or_on_the_box_under_the_pointer \
      tests/test_viewer_browser.py::test_the_zoom_number_reads_100_where_each_view_opens_and_after_a_click_on_it \
      tests/test_viewer_browser.py::test_where_no_place_clears_a_boxs_lines_its_card_lies_on_the_fewest \
      tests/test_viewer_browser.py::test_with_a_box_picked_resting_on_another_shows_its_card_and_draws_none_of_its_lines

A break whose text is no longer found stops the check at once: the code moved, so update the file.
