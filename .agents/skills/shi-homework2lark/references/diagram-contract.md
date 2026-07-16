# Diagram Contract

## Routing

When an original or variant requires a visual to be solvable, call the companion Skill `wumu-jihe-html` using the teacher-facing intent “这道题画张图”. Do not ask a general raster model to guess precise mathematical relations when a deterministic geometry representation is possible.

Before routing, inspect `questionStemImageCount`, which counts `错题题目.题干图片`, not the complete crop in `图片题目`. A text-only original defaults to text-only variants. An original with a stem image still receives a new diagram only when the variant depends on a table, geometry figure, number line, chart, image choice or another non-text condition. This is a cost-saving default, not a hard prohibition: an explicit teacher/Agent design may intentionally change a text question into a visual representation, but the preview must state that choice.

## Work Item

Before drawing, derive:

- logical question ID and optional variant number;
- objects and labels;
- mathematical definitions and constraints;
- free versus derived objects;
- values that may change from the original;
- visual-only choices such as spacing and color.

If an ambiguity changes topology, equality, perpendicular/parallel relations, scale meaning, angle, quantity or answer, ask the teacher. Cosmetic ambiguity can be resolved locally.

## Output

`wumu-jihe-html` produces an offline editable HTML. Open it, inspect the full question relation, then export PNG from the editor. Keep:

- HTML locally as the editable source;
- PNG as the student-facing diagram and Base attachment;
- a short constraint description in the generation payload and local editable artifact; it is not stored as a separate Base column.

Use relative session paths such as:

```text
session/diagrams/problem_xxx-v2.html
session/diagrams/problem_xxx-v2.png
```

## Quality Gate

Before Base upload verify:

- every number, object, label and relation matches the variant text;
- no answer or hidden solution is shown in the student diagram;
- the diagram contains all necessary conditions and no unsupported condition;
- labels remain legible in Word/PDF output;
- the PNG is the exported state of the reviewed editable HTML.

An image file is not a new problem. It attaches to the same numbered variant. When a diagram is declared, the write must stop unless the reviewed PNG exists, uploads successfully and reads back as exactly one attachment on that variant row. The variant table has no second approval or exception field; an incomplete image transaction must not be reported as a completed write.
