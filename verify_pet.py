"""Exercise the real Tk frame loader and all pet states before packaging."""
import json
from pathlib import Path
from PIL import Image, ImageGrab
import app

QA = Path(__file__).resolve().parent / 'qa'
QA.mkdir(exist_ok=True)
app.settings_path = lambda: QA / 'smoke-settings.json'
pet = app.OrangeCatPet()
results = {}
try:
    assert len(pet.frames) == 9
    for scale in (0.5, 0.8, 1.1):
        pet._set_scale(scale)
        for state, frames in pet.frames.items():
            assert len(frames) == 4
            pet._enter_state(state, 1.4)
            for elapsed in (0.0, 0.35, 0.7, 1.05, 1.4):
                pet._update_frame(elapsed)
                pet.root.update_idletasks()
            results[f'{state}@{scale}'] = 'ok'
    pet._set_scale(1.1)
    pet.paused = True
    pet.x, pet.base_y = 100.0, 100.0
    pet._set_window_position(pet.x, pet.base_y)
    pet._enter_state('idle', 3)
    pet._update_frame(0)
    pet.root.update()
    box = (100, 100, 100 + pet.window_w, 100 + pet.window_h)
    ImageGrab.grab(bbox=box).save(QA / 'desktop-preview.png')
    atlas = Image.open(app.resource_path('spritesheet.png')).convert('RGBA')
    assert atlas.size == (768, 1664)
    for row in range(8):
        for col in range(4):
            alpha = atlas.crop((col*192,row*208,(col+1)*192,(row+1)*208)).getchannel('A')
            box = alpha.point(lambda v: 255 if v >= 72 else 0).getbbox()
            assert box and box[0] >= 5 and box[2] <= 187 and box[1] >= 5 and box[3] <= 203, (row,col,box)
    results['atlas_dimensions_and_margins'] = 'ok'
    (QA / 'verification.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))
finally:
    pet.quit()
