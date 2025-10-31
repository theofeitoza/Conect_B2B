document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search-input');
    const searchResults = document.getElementById('search-results');

    if (searchInput) {
        searchInput.addEventListener('input', function() {
            const query = searchInput.value;

            if (query.length < 2) {
                searchResults.style.display = 'none';
                return;
            }

            fetch(`/autocomplete_search?query=${query}`)
                .then(response => response.json())
                .then(data => {
                    searchResults.innerHTML = '';
                    if (data.length > 0) {
                        searchResults.style.display = 'block';
                        data.forEach(item => {
                            const li = document.createElement('li');
                            li.textContent = item;
                            li.addEventListener('click', () => {
                                searchInput.value = item;
                                searchResults.style.display = 'none';
                                searchInput.form.submit();
                            });
                            searchResults.appendChild(li);
                        });
                    } else {
                        searchResults.style.display = 'none';
                    }
                });
        });

        document.addEventListener('click', function(e) {
            if (e.target !== searchInput) {
                searchResults.style.display = 'none';
            }
        });
    }
});