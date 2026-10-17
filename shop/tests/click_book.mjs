import fs from "node:fs";

const html = fs.readFileSync(0, "utf8");
const start = html.indexOf("<script>");
const end = html.indexOf("</script>", start);
if (start < 0 || end < 0) {
  console.error("homepage has no carousel script");
  process.exit(1);
}
const code = html.slice(start + "<script>".length, end);
const slug = process.argv[2];
if (!slug) {
  console.error("pass a book slug");
  process.exit(1);
}
const href = `/boeken/${slug}`;
if (!html.includes(`href="${href}"`)) {
  console.error("homepage card does not link to the buying page");
  process.exit(1);
}

class ClassList {
  constructor(names) {
    this.values = new Set(names.filter(Boolean));
  }
  add(name) { this.values.add(name); }
  remove(name) { this.values.delete(name); }
  contains(name) { return this.values.has(name); }
  toggle(name, on) {
    const next = on === undefined ? !this.values.has(name) : on;
    if (next) this.values.add(name);
    else this.values.delete(name);
  }
}

class El {
  constructor(tag, attrs = {}) {
    this.tag = tag;
    this.id = attrs.id || "";
    this.attrs = { ...attrs };
    this.children = [];
    this.parent = null;
    this.classList = new ClassList((attrs.class || "").split(/\s+/));
    this.listeners = {};
    this.dataset = {};
    this.scrollLeft = 0;
    this.clientWidth = 1000;
    this.offsetLeft = 0;
    this.offsetWidth = 256;
    this.textContent = "";
  }
  append(child) {
    child.parent = this;
    this.children.push(child);
    return child;
  }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }
  closest(selector) {
    let node = this;
    while (node) {
      if (matches(node, selector)) return node;
      node = node.parent;
    }
    return null;
  }
  querySelector(selector) {
    return walk(this).find((node) => matches(node, selector)) || null;
  }
  querySelectorAll(selector) {
    return walk(this).filter((node) => matches(node, selector));
  }
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  setPointerCapture() {}
}

function walk(el) {
  const out = [];
  for (const child of el.children) {
    out.push(child, ...walk(child));
  }
  return out;
}

function matches(el, selector) {
  if (selector === "[data-week]") return Object.prototype.hasOwnProperty.call(el.attrs, "data-week");
  if (selector === "a.book") return el.tag === "a" && el.classList.contains("book");
  if (selector.startsWith(".")) return el.classList.contains(selector.slice(1));
  return false;
}

function boot() {
  const rail = new El("div", { id: "home-rail" });
  const card = rail.append(new El("a", { class: "card book", href }));
  const title = card.append(new El("h3"));
  const document = new El("document");
  document.append(rail);
  const location = { href: "" };
  location.assign = (url) => { location.href = url; };
  const window = {
    location,
    addEventListener() {},
  };
  globalThis.document = document;
  globalThis.window = window;
  document.getElementById = (id) => walk(document).find((node) => node.id === id) || null;
  eval(code);
  return { rail, title, location };
}

function fire(el, type, extras) {
  const event = {
    button: 0,
    pointerType: "mouse",
    clientX: 0,
    pointerId: 1,
    defaultPrevented: false,
    ...extras,
  };
  event.target = extras.target || el;
  event.preventDefault = () => { event.defaultPrevented = true; };
  event.stopPropagation = () => {};
  for (const fn of el.listeners[type] || []) fn(event);
  return event;
}

const click = boot();
fire(click.rail, "pointerdown", { target: click.title, clientX: 10 });
fire(click.rail, "pointerup", { target: click.rail, clientX: 12 });
console.log(`click ${click.location.href}`);

const drag = boot();
fire(drag.rail, "pointerdown", { target: drag.title, clientX: 10 });
fire(drag.rail, "pointermove", { target: drag.rail, clientX: 40 });
fire(drag.rail, "pointerup", { target: drag.rail, clientX: 40 });
const blocked = fire(drag.rail, "click", { target: drag.title });
console.log(drag.location.href ? `drag followed ${drag.location.href}` : "drag stayed");
console.log(blocked.defaultPrevented ? "drag click blocked" : "drag click followed");
