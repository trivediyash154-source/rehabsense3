# RehabSense — Image Prompt Pack

Art-directed prompts for commissioning or generating the photographic layer.

**Status: not yet produced.** `public/` contains no photography. No image was
generated or downloaded for this repository, because every candidate would
either (a) require a licence this project does not hold, or (b) risk being read
as a real RehabSense patient or as real hardware. The prompts below are the
specification; the treatment component (`components/media/PhotoPlate.tsx`)
renders a designed plate until approved assets exist, and accepts them without
further layout work once they do.

---

## Non-negotiable constraints for every prompt

Append to every prompt:

> Editorial healthcare photography, natural available light, realistic skin
> texture and fabric detail, shallow-to-medium depth of field, muted
> desaturated palette with cool blue-grey shadows, documentary tone. No text,
> no logos, no watermarks, no UI overlays, no visible brand names.

Negative prompt for every image:

> cheesy stock smile, posed handshake, doctor holding tablet, surgical theatre,
> blood, wounds, exposed anatomy, medical horror, plastic AI skin, extra
> fingers, malformed hands, warped knees, impossible joint angles, glowing
> holograms, sci-fi HUD, exaggerated bokeh, HDR halos, oversaturated teal-orange
> grade, fake sensor hardware, fictional device branding

**Two rules that override aesthetics:**

1. **Never depict the RehabSense device.** The hardware is unbuilt. Any strap or
   module in frame must read as generic athletic/orthopaedic equipment, never as
   a specific product. Where the real assembly must be shown, use the 3D scene
   or the Lite stage instead — those are honest about being conceptual.
2. **Never imply a real patient or outcome.** No before/after pairs, no recovery
   claims in caption, no clinical setting that reads as a named institution.

Release requirement: model release covering commercial and web use, plus a
property release for any identifiable clinical interior.

---

## Prompt 1 — Landing hero context

**Use:** full-bleed plate behind the hero's left column, heavily overlaid.

> A person in their late twenties walking slowly across a wide, quiet
> rehabilitation studio, photographed from the side at knee height with a 35mm
> lens. Neutral grey athletic shorts, bare lower legs, plain trainers. Motion
> blur on the trailing leg only; the supporting leg sharp. Large north-facing
> window out of frame to camera-left throws soft directional daylight across a
> pale concrete floor; deep cool shadow fills the right two-thirds. Composition:
> subject occupies the lower-right third, upper-left two-thirds is empty wall
> and falloff for headline text. Mood: quiet, ordinary, mid-effort — not
> triumphant. Aspect ratio 16:9.

**Text-safe region:** upper-left 60% × 70%.

---

## Prompt 2 — Patient and physiotherapist

**Use:** "For physiotherapists" audience panel.

> A physiotherapist in their forties crouched beside a seated patient in their
> thirties, both looking at the patient's knee rather than at the camera. The
> clinician's hand rests just above the knee, guiding rather than manipulating.
> Plain clinical room, pale walls, a treatment table edge in soft foreground
> blur. 50mm lens at eye level of the crouching clinician, f/2.8. Soft
> overcast daylight from a window behind camera. Both faces partially turned
> away — this is about attention, not portraiture. Muted palette: sage, warm
> grey, skin tones. Aspect ratio 4:5.

**Text-safe region:** none; use as a bleed image with a caption strip.

---

## Prompt 3 — Knee rehabilitation exercise

**Use:** exercise context; "Range of motion" feature module.

> Close-medium shot of a seated person extending one leg to roughly ninety
> degrees, hands resting on the chair edge, photographed from the side at knee
> height with an 85mm lens at f/2.5. Only the torso-down is in frame. Simple
> dark athletic shorts, bare knee, clean skin texture with realistic tone
> variation. Single soft key light from camera-left with a large falloff to
> near-black on the right. Background: unlit studio grey, no props. Emphasis on
> the geometry of the joint angle. Aspect ratio 3:2.

**Text-safe region:** right 35% (shadow falloff).

---

## Prompt 4 — Sensor fitting

**Use:** "Wear" step of the journey; sensor-anatomy section.

> Macro shot of two hands fastening a plain neoprene strap around a thigh, just
> above the knee. 100mm macro lens at f/4, focus on the strap's velcro texture
> and the fingertips. The strap is unbranded matte black with a simple loop —
> no electronics, no housing, no logo visible. Skin and fabric texture both
> crisp. Cool directional light raking across the material from camera-right.
> Background falls to soft dark grey. Aspect ratio 1:1.

**Critical:** the strap must be visibly generic. Do not render any module,
LED, cable or enclosure.

---

## Prompt 5 — Walking rehabilitation

**Use:** WALK exercise card; gait-timing feature.

> A person walking directly away from camera down a bright corridor, framed
> from the waist down, 70mm lens compressing the perspective. Even overhead
> daylight through a glazed roof. Both legs visible mid-stride so the
> asymmetry between them is legible. Pale terrazzo floor with soft reflections.
> Cool neutral grade, low contrast. Aspect ratio 2:1 letterbox.

**Text-safe region:** upper 30% (ceiling falloff).

---

## Prompt 6 — Squat rehabilitation

> Side view of a person in a controlled partial squat, hands extended forward
> for balance, photographed at hip height with a 50mm lens. Plain grey marled
> shorts and t-shirt. Studio backdrop in warm mid-grey, single large softbox
> camera-left, subtle rim light separating the calf from the background. The
> pose is mid-descent and stable, not strained. Aspect ratio 4:5.

---

## Prompt 7 — Sit-to-stand

> A person rising from a plain wooden chair, caught at the moment of hip
> extension, weight forward, one hand still on the chair arm. Three-quarter
> rear view, 35mm lens at chest height. Domestic setting implied by a plain
> wall and skirting board, nothing decorative. Warm late-afternoon window light
> from the left, long soft shadow across the floor. Aspect ratio 3:4.

---

## Prompt 8 — Step-up

> A person stepping up onto a low plyometric box, photographed from the side at
> knee height, 50mm lens. The leading knee is flexed and loaded; the trailing
> foot is still in contact with the floor. Gym floor of dark rubber matting,
> pale wall behind. Cool overhead light with a soft secondary fill. No mirrors,
> no equipment clutter. Aspect ratio 3:2.

---

## Prompt 9 — Single-leg balance

> A person balancing on one leg, arms slightly abducted, framed from the chest
> down against a plain pale wall. 85mm lens, f/2.8, camera at hip height. The
> lifted foot hovers a few centimetres off the floor. Even soft light with a
> gentle gradient down the wall. Stillness is the subject. Aspect ratio 9:16
> for the mobile exercise card.

---

## Prompt 10 — Clinician reviewing movement data

**Use:** physiotherapist workspace; report preview.

> Over-the-shoulder view of a clinician in their fifties studying a large
> monitor in a dim consultation room, face lit only by screen light. The screen
> content is out of focus and abstract — coloured line traces on dark, with no
> legible interface. 35mm lens at f/2, camera slightly behind and above the
> shoulder. Cool blue key from the display, warm practical lamp far right for
> separation. Aspect ratio 16:9.

**Critical:** the screen must remain illegible. A readable interface would
read as a real RehabSense product screenshot.

---

## Prompt 11 — Hardware close-up (materials only)

**Use:** device / technical-foundation section.

> Extreme macro of anonymous electronics-grade materials: a matte black
> injection-moulded shell edge, a strip of neoprene webbing, and a brushed
> aluminium fastener, arranged as a still life on a dark grey seamless surface.
> 100mm macro at f/8 focus-stacked so all textures are sharp. Hard raking light
> from the left, deep shadow to the right. No circuit boards, no components, no
> screens, no branding. Aspect ratio 1:1.

**Critical:** materials only. This must never look like an assembled product.

---

## Prompt 12 — Empty dashboard state

> A single empty chair beside a window in a quiet rehabilitation room, early
> morning, nobody present. Wide 28mm lens, low contrast, pale blue-grey cast.
> Large areas of flat wall and floor. Melancholy but calm — a room waiting for
> a session. Aspect ratio 16:9.

**Text-safe region:** centre 50%.

---

## Prompt 13 — Report cover

> Abstract overhead shot of a pale grey paper document on a dark desk, lit by a
> single hard window light that throws a soft-edged rectangle across it. The
> paper is blank. 50mm lens, slight perspective, deep shadow at the frame
> edges. Aspect ratio 3:4 portrait.

**Use:** blends into the anatomical motion trace on the receipt cover.

---

## Prompt 14 — Progress milestone

> A person sitting on the edge of a treatment table lacing a trainer,
> photographed from across the room with a 85mm lens so the surroundings
> compress. Framed small in the lower third of a large calm interior. Soft
> daylight. The mood is unremarkable competence — a routine step, not a
> victory. Aspect ratio 21:9.

**Avoid:** raised arms, celebration, eye contact.

---

## Prompt 15 — Patient progress moment

> Two people walking side by side along a hospital corridor away from camera,
> one slightly favouring a leg, the other matching their pace. Framed from
> behind at full height, 50mm lens. Bright, slightly overexposed daylight at
> the corridor's end. Quiet companionship rather than assistance. Aspect ratio
> 16:9.

---

## Integration

```tsx
import { PhotoPlate } from "@/components/media/PhotoPlate";

<PhotoPlate
  src="/media/hero-walk.jpg"     // omit until an approved asset exists
  alt="A person walking across a rehabilitation studio."
  caption="Illustrative photography · not a RehabSense patient"
  tone="cool"
  ratio="16 / 9"
/>
```

- Dark theme: navy multiply overlay, cyan/violet edge light, fine grain, a slow
  light pass across the plate.
- Light theme: pale blue wash, cobalt hairline frame, warm daylight lift,
  cleaner crop, no grain.
- Every plate carries a caption. Any photograph shown in product context must
  state that it is illustrative and not a RehabSense patient.
