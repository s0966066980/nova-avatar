import unittest

import numpy as np

from src.avatars.musetalk.avatar_transition import AvatarTransitionController, TransitionState
from src.avatars.musetalk.mouth_continuity import MouthContinuityController


class AvatarTransitionTests(unittest.TestCase):
    def make_controller(self, *, frames=8, crossfade=2, threshold=18.0):
        source = [np.full((20, 20, 3), value, np.uint8) for value in range(frames)]
        masks = [np.zeros((20, 20), np.uint8) for _ in source]
        for mask in masks:
            mask[8:14, 7:13] = 255
        mouth = MouthContinuityController(source, masks, gap_grace_frames=0, settling_frames=5)
        return AvatarTransitionController(source, masks, None, [(4, 3, 16, 14)] * frames,
                                          mouth_controller=mouth, settling_min_frames=4,
                                          settling_max_frames=6, micro_crossfade_frames=crossfade,
                                          micro_crossfade_fullframe_max_diff=threshold), source

    def compose(self, controller, frame, index, speech, generation=1, frame_type=None):
        return controller.compose(frame, index=index, is_speech=speech,
                                  frame_type=0 if speech else (1 if frame_type is None else frame_type),
                                  eventpoint={"generation": generation})

    def test_speech_passes_through_and_enters_speaking(self):
        controller, source = self.make_controller()
        generated = np.full_like(source[0], 180)
        output = self.compose(controller, generated, 0, True)
        self.assertEqual(controller.state, TransitionState.SPEAKING)
        self.assertTrue(np.array_equal(output, generated))

    def test_speech_to_idle_starts_settling(self):
        controller, source = self.make_controller()
        self.compose(controller, np.full_like(source[0], 200), 0, True)
        self.compose(controller, source[1], 1, False)
        self.assertEqual(controller.state, TransitionState.SETTLING)

    def test_phase_match_selects_best_candidate_within_planned_window(self):
        controller, source = self.make_controller()
        descriptor = np.zeros((64, 64), np.float32)
        controller._source_pose_descriptors = tuple(
            np.full((64, 64), value, np.float32)
            for value in (0.0, 0.0, 0.0, 0.0, 0.5, 0.1, 0.4, 0.0)
        )
        planned, index, _ = controller._plan_idle_return(source[0], 1)
        self.assertEqual(planned, 5)
        self.assertEqual(index, 5)

    def test_compose_never_changes_input_cursor(self):
        controller, source = self.make_controller()
        self.compose(controller, np.full_like(source[0], 200), 10, True)
        for index in (11, 12, 13, 14):
            self.compose(controller, source[index % len(source)], index, False)
            self.assertEqual(controller._last_source_index, index % len(source))

    def test_pingpong_prediction_includes_duplicate_endpoints(self):
        controller, _ = self.make_controller(frames=4)
        seen = []
        index, direction = 0, 1
        for _ in range(10):
            seen.append(index)
            index, direction = controller._next_pingpong_index(index, direction, 4)
        self.assertEqual(seen, [0, 1, 2, 3, 3, 2, 1, 0, 0, 1])

    def test_settling_is_monotonic_and_ends_at_idle_mouth(self):
        controller, source = self.make_controller(crossfade=0)
        generated = source[0].copy()
        generated[8:14, 7:13] = 200
        self.compose(controller, generated, 0, True)
        first = self.compose(controller, source[1], 1, False)
        planned = controller._settling_total
        values = [int(first[8:14, 7:13].mean())]
        values.extend(
            int(self.compose(controller, source[i], i, False)[8:14, 7:13].mean())
            for i in range(2, planned + 1)
        )
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(values[-1], int(source[planned][8:14, 7:13].mean()))

    def test_speech_cancels_settling(self):
        controller, source = self.make_controller()
        self.compose(controller, np.full_like(source[0], 200), 0, True)
        self.compose(controller, source[1], 1, False)
        self.assertEqual(controller.state, TransitionState.SETTLING)
        self.compose(controller, np.full_like(source[2], 180), 2, True)
        self.assertEqual(controller.state, TransitionState.SPEAKING)

    def test_speech_cancels_crossfade(self):
        controller, source = self.make_controller()
        self.compose(controller, np.full_like(source[0], 200), 0, True)
        self.compose(controller, source[1], 1, False)
        for index in range(2, 9):
            self.compose(controller, source[index % len(source)], index % len(source), False)
            if controller.state == TransitionState.CROSSFADING:
                break
        self.assertEqual(controller.state, TransitionState.CROSSFADING)
        self.compose(controller, np.full_like(source[5], 170), 5, True)
        self.assertEqual(controller.state, TransitionState.SPEAKING)

    def test_generation_change_drops_old_speech_frame(self):
        controller, source = self.make_controller()
        self.compose(controller, np.full_like(source[0], 200), 0, True, generation=1)
        output = self.compose(controller, source[1], 1, False, generation=2)
        self.assertTrue(np.array_equal(output, source[1]))
        self.assertIsNone(controller._last_speech_frame)

    def test_crossfade_final_frame_is_current_target(self):
        controller, source = self.make_controller(crossfade=2)
        controller.state = TransitionState.CROSSFADING
        controller._crossfade_origin = np.full_like(source[0], 200)
        first = controller._apply_micro_crossfade(source[1], 1)
        final = controller._apply_micro_crossfade(source[2], 2)
        self.assertFalse(np.array_equal(first, source[1]))
        self.assertTrue(np.array_equal(final, source[2]))

    def test_ghosting_guard_is_mask_only(self):
        controller, source = self.make_controller(crossfade=2, threshold=0.0)
        controller.state = TransitionState.CROSSFADING
        controller._crossfade_origin = np.full_like(source[0], 200)
        target = source[1].copy()
        output = controller._apply_micro_crossfade(target, 1)
        self.assertEqual(int(output[0, 0].mean()), int(target[0, 0].mean()))

    def test_custom_frame_bypasses_transition(self):
        controller, source = self.make_controller()
        self.compose(controller, np.full_like(source[0], 200), 0, True)
        output = self.compose(controller, source[1], 1, False, frame_type=2)
        self.assertEqual(controller.state, TransitionState.IDLE)
        self.assertTrue(np.array_equal(output, source[1]))

    def test_reset_clears_all_transition_state(self):
        controller, source = self.make_controller()
        self.compose(controller, np.full_like(source[0], 200), 0, True)
        controller.reset()
        self.assertEqual(controller.state, TransitionState.IDLE)
        self.assertIsNone(controller._previous_output)
        self.assertIsNone(controller._last_speech_frame)
        self.assertIsNone(controller._crossfade_origin)
        self.assertIsNone(controller._generation)

    def test_source_frames_are_immutable(self):
        controller, source = self.make_controller()
        before = [frame.copy() for frame in source]
        self.compose(controller, np.full_like(source[0], 200), 0, True)
        for index in range(1, 7):
            self.compose(controller, source[index], index, False)
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(before, source)))


if __name__ == "__main__":
    unittest.main()
