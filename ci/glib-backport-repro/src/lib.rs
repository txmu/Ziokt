#[cfg(test)]
mod tests {
    use glib::variant::ToVariant;

    #[test]
    fn optimized_variant_string_iterator_preserves_all_out_pointers() {
        let expected: Vec<String> = (0..128).map(|i| format!("member-{i}-📘")).collect();
        let variant = expected.to_variant();
        let actual: Vec<&str> = variant.array_iter_str().unwrap().collect();
        assert_eq!(actual, expected.iter().map(String::as_str).collect::<Vec<_>>());
        let mut iter = variant.array_iter_str().unwrap();
        assert_eq!(iter.next(), Some(expected[0].as_str()));
        assert_eq!(iter.next_back(), Some(expected[127].as_str()));
        assert_eq!(iter.count(), 126);
    }
}
