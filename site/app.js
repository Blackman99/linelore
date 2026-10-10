(function () {
  var root = document.documentElement;
  var motion = root.classList.contains('motion');
  var hero = document.getElementById('hero');
  var line = document.getElementById('line');
  var seg = document.getElementById('seg');
  var svg = document.getElementById('leaders');
  var answers = [].slice.call(document.querySelectorAll('.ans'));
  var why = document.querySelector('.why');
  var NS = 'http://www.w3.org/2000/svg';
  var drawn = !motion;

  // split the code line into characters (seg keeps its own span)
  var chars = [];
  function split(node) {
    [].slice.call(node.childNodes).forEach(function (n) {
      if (n.nodeType === 3) {
        var frag = document.createDocumentFragment();
        n.textContent.split('').forEach(function (ch) {
          var s = document.createElement('span'); s.className = 'c'; s.textContent = ch;
          frag.appendChild(s); chars.push(s);
        });
        node.replaceChild(frag, n);
      } else if (n.nodeType === 1) split(n);
    });
  }
  split(line);

  // orange leader lines: trunk from the selected segment down, a branch to each numeral
  function off(el, stop) { // layout offset of el inside stop, ignoring transforms
    var x = 0, y = 0;
    while (el && el !== stop) { x += el.offsetLeft; y += el.offsetTop; el = el.offsetParent; }
    return { x: x, y: y };
  }
  function leaders() {
    var hb = hero.getBoundingClientRect();
    var sb = seg.getBoundingClientRect();
    var ob = answers[0].parentNode.getBoundingClientRect(); // the <ol>, never transformed
    var ol = answers[0].parentNode;
    var x = Math.min(sb.left + Math.min(sb.width / 2, 60), ob.left + off(answers[0], ol).x - 14) - hb.left;
    var y0 = sb.bottom - hb.top + 6;
    svg.setAttribute('viewBox', '0 0 ' + hb.width + ' ' + hb.height);
    svg.textContent = '';
    answers.forEach(function (a, i) {
      var num = a.querySelector('.num'); // offsets ignore the slide-in transform
      var o = off(num, ol);
      var y = ob.top + o.y - hb.top + num.offsetHeight * 0.45;
      var x1 = ob.left + o.x - hb.left - 8;
      var p = document.createElementNS(NS, 'path');
      p.setAttribute('d', 'M' + x + ' ' + y0 + 'V' + y + 'H' + x1);
      var len = (y - y0) + (x1 - x);
      p.style.strokeDasharray = len; p.style.strokeDashoffset = drawn || a.classList.contains('in') ? 0 : len;
      p.style.transitionDelay = (i * 0.09) + 's';
      svg.appendChild(p);
      var r = document.createElementNS(NS, 'rect');
      r.setAttribute('x', x1 - 1); r.setAttribute('y', y - 5); r.setAttribute('width', 10); r.setAttribute('height', 10);
      if (!(drawn || a.classList.contains('in'))) r.style.opacity = 0;
      svg.appendChild(r);
    });
    var tick = document.createElementNS(NS, 'rect');
    tick.setAttribute('x', x - 5); tick.setAttribute('y', y0 - 5); tick.setAttribute('width', 10); tick.setAttribute('height', 10);
    svg.appendChild(tick);
    if (!drawn) tick.style.opacity = 0;
  }

  function showLeaders() {
    var paths = [].slice.call(svg.querySelectorAll('path'));
    var rects = [].slice.call(svg.querySelectorAll('rect'));
    rects[rects.length - 1].style.opacity = 1;
    answers.forEach(function (a, i) {
      setTimeout(function () {
        paths[i].style.strokeDashoffset = 0;
        setTimeout(function () { rects[i].style.opacity = 1; a.classList.add('in'); }, 260);
      }, i * 230);
    });
    setTimeout(function () { why.classList.add('in'); drawn = true; }, answers.length * 230 + 400);
  }

  function intro() {
    hero.classList.add('go');
    // 1. the line, very large, letter-spaced across the measure
    var avail = hero.clientWidth - 48;
    var natural = line.getBoundingClientRect().width;
    var big = Math.max(1.2, Math.min(3.2, avail / natural));
    line.style.transform = 'scale(' + big + ')';
    // 2. break it apart
    setTimeout(function () {
      var n = chars.length;
      chars.forEach(function (c, i) {
        var dx = (i - n / 2) * 0.09, dy = (i % 3 - 1) * 0.42;
        c.style.transitionDelay = (Math.abs(i - n / 2) * 0.008) + 's';
        c.style.transform = 'translate(' + dx + 'em,' + dy + 'em) rotate(' + ((i % 5) - 2) * 4 + 'deg)';
      });
    }, 520);
    // 3. snap back to reading size, select the segment
    setTimeout(function () {
      line.style.transform = 'scale(1)';
      chars.forEach(function (c) { c.style.transitionDelay = '0s'; c.style.transform = ''; });
      seg.classList.add('on');
    }, 1250);
    // 4. draw leaders to 01-04
    setTimeout(function () { leaders(); requestAnimationFrame(function () { requestAnimationFrame(showLeaders); }); }, 1850);
  }

  if (motion) {
    requestAnimationFrame(intro);
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
      }, { rootMargin: '0px 0px -12% 0px' });
      [].slice.call(document.querySelectorAll('.hop, .sect-h')).forEach(function (el) { io.observe(el); });
    } else {
      [].slice.call(document.querySelectorAll('.hop, .sect-h')).forEach(function (el) { el.classList.add('in'); });
    }
  } else {
    leaders();
  }
  var rt;
  window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(leaders, 120); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { if (drawn) leaders(); });

  var copy = document.getElementById('copy');
  copy.addEventListener('click', function () {
    var t = copy.getAttribute('data-text');
    if (navigator.clipboard) navigator.clipboard.writeText(t).catch(function () {});
    copy.classList.add('done'); copy.textContent = 'Copied';
    setTimeout(function () { copy.classList.remove('done'); copy.textContent = 'Copy install command'; }, 1800);
  });
})();
