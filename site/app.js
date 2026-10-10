(function(){
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  cards.forEach(function(card){
    var tab = card.querySelector('.tab');
    tab.setAttribute('role','button'); tab.tabIndex = 0;
    function pull(){ cards.forEach(function(c){c.classList.remove('front')}); card.classList.add('front'); }
    tab.addEventListener('click', pull);
    tab.addEventListener('keydown', function(e){ if(e.key==='Enter'||e.key===' '){e.preventDefault();pull();} });
  });
  var slip = document.getElementById('slipstamp');
  document.getElementById('copy').addEventListener('click', function(){
    var t='pipx install git+https://github.com/Blackman99/linelore';
    if(navigator.clipboard) navigator.clipboard.writeText(t);
    slip.classList.remove('on'); void slip.offsetWidth; slip.classList.add('on'); this.textContent='Copied';
  });
  if(reduce) return;
  document.documentElement.classList.add('js');
  function type(el, done){
    var full = el.textContent; el.textContent=''; el.classList.add('typed'); var i=0;
    (function step(){ el.textContent = full.slice(0, i+=2); if(i<full.length) setTimeout(step, 14); else done(); })();
  }
  cards.forEach(function(card, n){
    setTimeout(function(){
      var lines = Array.prototype.slice.call(card.querySelectorAll('.t'));
      (function next(k){
        if(k>=lines.length){ var s=card.querySelector('.stamp'); if(s) s.classList.add('on'); return; }
        type(lines[k], function(){ next(k+1); });
      })(0);
    }, n*900 + 450);
  });
})();
