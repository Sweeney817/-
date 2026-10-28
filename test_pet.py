import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app


class PetTests(unittest.TestCase):
    def test_invalid_settings_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            pet = app.OrangeCatPet.__new__(app.OrangeCatPet)
            with patch.object(app, 'settings_path', return_value=path):
                path.write_text(json.dumps({'scale': None, 'x': 'bad', 'y': float('nan'), 'topmost': 'yes'}))
                self.assertEqual(pet._load_settings(), {})
                path.write_text('[]')
                self.assertEqual(pet._load_settings(), {})
                path.write_text(json.dumps({'scale': 0.8, 'x': -1200, 'topmost': False}))
                self.assertEqual(pet._load_settings(), {'scale': 0.8, 'x': -1200, 'topmost': False})

    def test_pause_restores_position_and_hides_bowl(self):
        pet = app.OrangeCatPet.__new__(app.OrangeCatPet)
        pet.paused = False
        pet.state = 'idle'
        pet.x, pet.base_y = -500, 200
        pet.canvas = Mock()
        pet._set_window_position = Mock()
        pet._update_frame = Mock()
        pet.toggle_pause()
        pet.canvas.itemconfigure.assert_any_call('bowl', state='hidden')
        pet.canvas.itemconfigure.assert_any_call('litter', state='hidden')
        pet._set_window_position.assert_called_once_with(-500, 200)
        pet._update_frame.assert_called_once_with(0, forced_state='idle')

    def test_interaction_resumes_and_uses_action(self):
        pet = app.OrangeCatPet.__new__(app.OrangeCatPet)
        pet.paused, pet.dragging = True, False
        pet._enter_state = Mock()
        pet._update_frame = Mock()
        pet._interact('drink', 6.0)
        self.assertFalse(pet.paused)
        pet._enter_state.assert_called_once_with('drink', 6.0)
        pet._update_frame.assert_called_once_with(0)

    def test_litter_is_chosen_when_due(self):
        pet = app.OrangeCatPet.__new__(app.OrangeCatPet)
        pet.litter_countdown = 0
        pet._enter_state = Mock()
        pet._choose_next_state()
        pet._enter_state.assert_called_once_with('litter')

    def test_litter_visual_phases(self):
        pet = app.OrangeCatPet.__new__(app.OrangeCatPet)
        pet.canvas = Mock()
        pet.state, pet.state_duration = 'litter', 12
        pet.frames = {'litter': list(range(8))}
        pet.image_item, pet.current_frame_key = 1, None
        for elapsed, frame in ((0, 0), (6, 4), (12, 7)):
            pet._update_frame(elapsed)
            pet.canvas.itemconfigure.assert_called_with(1, image=frame)


if __name__ == '__main__':
    unittest.main()
